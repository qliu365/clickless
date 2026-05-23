"""
存储模块 - 将录制的流程保存为 JSON，并支持加载、列表、删除。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class FlowStorage:
    """管理 flows/ 目录下的流程 JSON 文件。"""

    def __init__(self, flows_dir: Path) -> None:
        self.flows_dir = Path(flows_dir)
        self.flows_dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, steps: List[dict]) -> Path:
        """
        保存流程到 JSON 文件。

        Args:
            name: 流程名称（显示用，也会写入 JSON）
            steps: 步骤列表

        Returns:
            保存的文件路径
        """
        name = name.strip()
        if not name:
            raise ValueError("流程名称不能为空")

        data = {
            "name": name,
            "steps": steps,
        }
        path = self._path_for_name(name)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def load(self, name: str) -> Dict[str, Any]:
        """按名称加载流程。"""
        path = self._path_for_name(name)
        if not path.exists():
            raise FileNotFoundError(f"流程不存在: {name}")
        return self._load_file(path)

    def load_by_path(self, path: Path) -> Dict[str, Any]:
        """按文件路径加载流程。"""
        return self._load_file(Path(path))

    def list_flows(self) -> List[Dict[str, Any]]:
        """
        列出所有已保存的流程。

        Returns:
            [{"name": "...", "filename": "...", "step_count": N}, ...]
        """
        flows: List[Dict[str, Any]] = []
        for path in sorted(self.flows_dir.glob("*.json")):
            try:
                data = self._load_file(path)
                flows.append(
                    {
                        "name": data.get("name", path.stem),
                        "filename": path.name,
                        "step_count": len(data.get("steps", [])),
                    }
                )
            except (json.JSONDecodeError, OSError):
                # 损坏的文件跳过，不阻断列表
                continue
        return flows

    def delete(self, name: str) -> bool:
        """
        删除指定流程文件。

        Returns:
            是否成功删除（文件不存在则返回 False）
        """
        path = self._path_for_name(name)
        if not path.exists():
            return False
        path.unlink()
        return True

    def exists(self, name: str) -> bool:
        """检查流程是否已存在。"""
        return self._path_for_name(name).exists()

    def _path_for_name(self, name: str) -> Path:
        """根据流程名生成安全的文件路径。"""
        safe = self._sanitize_filename(name)
        return self.flows_dir / f"{safe}.json"

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """去掉文件名非法字符，保留中文等 Unicode。"""
        # Windows / macOS 通用非法字符
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())
        return safe or "unnamed"

    @staticmethod
    def _load_file(path: Path) -> Dict[str, Any]:
        """从 JSON 文件读取流程。"""
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if "steps" not in data:
            data["steps"] = []
        if "name" not in data:
            data["name"] = path.stem
        return data
