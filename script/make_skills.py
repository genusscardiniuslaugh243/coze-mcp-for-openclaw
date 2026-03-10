import os
import sys
import argparse
import asyncio
import shutil
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import httpx

load_dotenv()

COZE_API_KEY = os.getenv("COZE_API_KEY")
WORKSPACE_ID = os.getenv("WORKSPACE_ID")
COZE_API_BASE = "https://api.coze.cn/v1"


def get_skills_dir() -> Path:
    skills_dir = os.getenv("OPENCLAW_SKILLS_DIR")
    if not skills_dir:
        print("错误: 未配置 OPENCLAW_SKILLS_DIR 环境变量")
        sys.exit(1)
    return Path(skills_dir)


def get_template_content() -> str:
    template_path = Path(__file__).parent.parent / "skill_template.md"
    if not template_path.exists():
        print(f"错误: 找不到模板文件 {template_path}")
        sys.exit(1)
    return template_path.read_text(encoding="utf-8")


async def get_workflow_list() -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        params = {
            "workspace_id": WORKSPACE_ID,
            "page_num": 1,
            "page_size": 50,
            "publish_status": "published_online"
        }
        
        headers = {
            "Authorization": f"Bearer {COZE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = await client.get(
            f"{COZE_API_BASE}/workflows",
            headers=headers,
            params=params
        )
        
        if response.status_code != 200:
            raise Exception(f"获取工作流列表失败: {response.text}")
        
        result = response.json()
        
        if result.get("code") != 0:
            raise Exception(f"API错误: {result.get('msg', '未知错误')}")
        
        workflow_dict = {}
        data = result.get("data", {})
        items = data.get("items", [])
        
        for workflow in items:
            workflow_name = workflow.get("workflow_name")
            workflow_id = workflow.get("workflow_id")
            if workflow_name and workflow_id:
                workflow_dict[workflow_name] = {
                    "workflow_id": workflow_id,
                    "workflow_name": workflow_name,
                    "description": workflow.get("description", ""),
                }
        
        return workflow_dict


async def get_workflow_detail(workflow_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {COZE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = await client.get(
            f"{COZE_API_BASE}/workflows/{workflow_id}",
            headers=headers,
            params={"include_input_output": "true"}
        )
        
        if response.status_code != 200:
            raise Exception(f"获取工作流详情失败: {response.text}")
        
        result = response.json()
        
        if result.get("code") != 0:
            raise Exception(f"API错误: {result.get('msg', '未知错误')}")
        
        return result.get("data", {})


def format_parameters(parameters: dict[str, Any]) -> str:
    if not parameters:
        return "无参数"
    
    lines = []
    for param_name, param_info in parameters.items():
        param_type = param_info.get("type", "unknown")
        param_desc = param_info.get("description", "无描述")
        required = param_info.get("required", False)
        
        required_mark = " (必填)" if required else " (可选)"
        lines.append(f" - `{param_name}` [{param_type}]{required_mark}: {param_desc}")
    
    return "\n".join(lines)


def generate_skill_content(template: str, workflow_name: str, workflow_description: str, parameters: dict[str, Any]) -> str:
    params_str = format_parameters(parameters)
    
    content = template.replace("{workflow_name}", workflow_name)
    content = content.replace("{workflow_description}", workflow_description or "无描述")
    content = content.replace("{workflow_params}", params_str)
    
    return content


async def main(update: bool = False):
    if not COZE_API_KEY:
        print("错误: 未配置 COZE_API_KEY 环境变量")
        sys.exit(1)
    
    if not WORKSPACE_ID:
        print("错误: 未配置 WORKSPACE_ID 环境变量")
        sys.exit(1)
    
    skills_dir = get_skills_dir()
    template = get_template_content()
    
    if not skills_dir.exists():
        skills_dir.mkdir(parents=True, exist_ok=True)
        print(f"创建技能目录: {skills_dir}")
    
    print("正在获取工作流列表...")
    workflows = await get_workflow_list()
    
    if not workflows:
        print("未找到已发布的工作流")
        return
    
    print(f"找到 {len(workflows)} 个已发布的工作流")
    
    created_count = 0
    skipped_count = 0
    updated_count = 0
    
    for workflow_name, workflow_info in workflows.items():
        workflow_id = workflow_info["workflow_id"]
        description = workflow_info.get("description", "")
        
        skill_folder = skills_dir / workflow_name
        skill_file = skill_folder / "SKILL.md"
        
        if skill_folder.exists():
            if not update:
                print(f"  跳过: {workflow_name} (文件夹已存在，使用 --update 来更新)")
                skipped_count += 1
                continue
            else:
                print(f"  更新: {workflow_name}")
                updated_count += 1
        else:
            skill_folder.mkdir(parents=True, exist_ok=True)
            print(f"  创建: {workflow_name}")
            created_count += 1
        
        try:
            detail = await get_workflow_detail(workflow_id)
            input_data = detail.get("input", {})
            parameters = input_data.get("parameters", {})
        except Exception as e:
            print(f"    警告: 获取参数失败 - {e}")
            parameters = {}
        
        content = generate_skill_content(template, workflow_name, description, parameters)
        skill_file.write_text(content, encoding="utf-8")
    
    print(f"\n完成! 创建: {created_count}, 更新: {updated_count}, 跳过: {skipped_count}")


async def remove_skills(workflow_names: str):
    skills_dir = get_skills_dir()
    
    if not skills_dir.exists():
        print(f"错误: 技能目录不存在: {skills_dir}")
        sys.exit(1)
    
    if workflow_names.lower() == "all":
        if not COZE_API_KEY:
            print("错误: 未配置 COZE_API_KEY 环境变量")
            sys.exit(1)
        
        if not WORKSPACE_ID:
            print("错误: 未配置 WORKSPACE_ID 环境变量")
            sys.exit(1)
        
        print("正在获取工作流列表...")
        workflows = await get_workflow_list()
        
        if not workflows:
            print("未找到已发布的工作流")
            return
        
        workflow_list = []
        for name in workflows.keys():
            skill_folder = skills_dir / name
            if skill_folder.exists() and skill_folder.is_dir():
                workflow_list.append(name)
        
        if not workflow_list:
            print("技能目录中没有对应的 Coze 工作流技能")
            return
    else:
        workflow_list = [name.strip() for name in workflow_names.split(",")]
        workflow_list = [name for name in workflow_list if name]
        
        if not workflow_list:
            print("错误: 未指定要删除的工作流名称")
            sys.exit(1)
        
        found = []
        not_found = []
        for name in workflow_list:
            skill_folder = skills_dir / name
            if skill_folder.exists() and skill_folder.is_dir():
                found.append(name)
            else:
                not_found.append(name)
        
        if not_found:
            print(f"警告: 以下技能不存在: {', '.join(not_found)}")
        
        if not found:
            print("没有找到可删除的技能")
            return
        
        workflow_list = found
    
    print(f"将删除以下 {len(workflow_list)} 个技能:")
    for name in workflow_list:
        print(f"  - {name}")
    
    confirm = input("\n确认删除? (y/N): ").strip().lower()
    if confirm != "y":
        print("已取消删除")
        return
    
    removed_count = 0
    failed_count = 0
    
    for name in workflow_list:
        skill_folder = skills_dir / name
        try:
            shutil.rmtree(skill_folder)
            print(f"  已删除: {name}")
            removed_count += 1
        except Exception as e:
            print(f"  删除失败: {name} - {e}")
            failed_count += 1
    
    print(f"\n完成! 删除: {removed_count}, 失败: {failed_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="为工作流创建技能文件夹")
    parser.add_argument("--update", action="store_true", help="更新已存在的技能文件夹")
    parser.add_argument("--remove", type=str, metavar="NAMES", help="删除指定的技能文件夹，支持逗号分隔多个名称，或使用 'all' 删除全部")
    args = parser.parse_args()
    
    if args.remove is not None:
        asyncio.run(remove_skills(args.remove))
    else:
        asyncio.run(main(update=args.update))
