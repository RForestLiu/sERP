"""
ImageTask 域 - 领域服务（纯业务逻辑，无 I/O 依赖）。
"""
from __future__ import annotations

import base64
import io
import struct
import ctypes
import logging
from datetime import datetime

from PIL import Image

logger = logging.getLogger(__name__)


TASK_TYPES = [
    {"id": "batch_translate", "name": "批量翻译图片", "icon": "\U0001f310", "description": "AI图片翻译，中→俄等", "available": True},
    {"id": "batch_crop_resize", "name": "批量裁剪/缩放", "icon": "✂️", "description": "按平台尺寸要求处理", "available": False},
    {"id": "generate_main_image", "name": "生成产品首图", "icon": "\U0001f3a8", "description": "白模图+产品信息→首图", "available": False},
    {"id": "batch_replace_product", "name": "批量替换产品图", "icon": "\U0001f504", "description": "用新产品图替换模板", "available": True},
]


# ── 任务名称生成 ──

def _generate_task_name(task_type: str, existing_names: list[str]) -> str:
    """根据类型和已有名称自动生成任务名称"""
    type_info = next((tt for tt in TASK_TYPES if tt["id"] == task_type), None)
    base_name = type_info["name"] if type_info else (task_type or "任务")
    n = 1
    while f"{base_name} {n}" in existing_names:
        n += 1
    return f"{base_name} {n}"


# ── 独立领域服务 ──

class CompressImageService:
    """图片压缩领域服务 — 接收图片字节流，返回压缩后的字节流"""

    @staticmethod
    def compress(image_data: bytes, max_size: int = 1_572_864) -> tuple[bytes, str]:
        """
        将图片压缩到 max_size 字节以下（默认 1.5MB）
        - 自动将 PNG/WebP 转为 JPEG 以获得更好压缩率
        - 自适应质量：从 85 开始递减，最低至 30
        - 若质量降到最低仍超标，则降低分辨率
        返回: (压缩后的字节数据, mime类型)
        """
        try:
            img = Image.open(io.BytesIO(image_data))

            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")

            quality = 85
            while quality >= 30:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                if buf.tell() <= max_size:
                    return buf.getvalue(), "image/jpeg"
                quality -= 5

            scale = 0.9
            while True:
                w, h = int(img.width * scale), int(img.height * scale)
                if w < 100 or h < 100:
                    break
                resized = img.resize((w, h), Image.LANCZOS)
                buf = io.BytesIO()
                resized.save(buf, format="JPEG", quality=30, optimize=True)
                if buf.tell() <= max_size:
                    return buf.getvalue(), "image/jpeg"
                scale *= 0.9

            return image_data, "image/jpeg"
        except Exception as e:
            logger.warning("Compress failed: %s", e)
            return image_data, "image/jpeg"


class CopyToClipboardService:
    """系统剪贴板领域服务 — Windows CF_HDROP 文件复制"""

    @staticmethod
    def copy_files(file_paths: list[str]):
        """将文件路径列表写入 Windows 系统剪贴板 CF_HDROP"""
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        user32 = ctypes.windll.user32
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL

        file_list = b""
        for p in file_paths:
            file_list += p.encode("utf-16-le") + b"\x00\x00"
        file_list += b"\x00\x00"

        dropfiles = struct.pack("Iiiii", 20, 0, 0, 0, 1)
        data = dropfiles + file_list

        GMEM_MOVEABLE = 0x0002
        GMEM_ZEROINIT = 0x0040
        hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
        if not hglobal:
            raise OSError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(hglobal)
        if not ptr:
            kernel32.GlobalFree(hglobal)
            raise OSError("GlobalLock failed")
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(hglobal)

        CF_HDROP = 15
        clipboard_open = False
        try:
            if not user32.OpenClipboard(None):
                raise OSError("OpenClipboard failed")
            clipboard_open = True
            if not user32.EmptyClipboard():
                raise OSError("EmptyClipboard failed")
            if not user32.SetClipboardData(CF_HDROP, hglobal):
                raise OSError("SetClipboardData failed")
            hglobal = None
        finally:
            if clipboard_open:
                user32.CloseClipboard()
            if hglobal:
                kernel32.GlobalFree(hglobal)


class FileManagementService:
    """文件管理领域服务"""

    @staticmethod
    def ensure_task_dirs(base_dir: str, task_id: str):
        """确保任务目录结构存在"""
        import os
        task_dir = os.path.join(base_dir, f"task_{task_id}")
        os.makedirs(task_dir, exist_ok=True)
        os.makedirs(os.path.join(task_dir, "source_images"), exist_ok=True)
        os.makedirs(os.path.join(task_dir, "drafts"), exist_ok=True)
        os.makedirs(os.path.join(task_dir, "generated"), exist_ok=True)

    @staticmethod
    def task_folder(base_dir: str, task_id: str) -> str:
        import os
        return os.path.join(base_dir, f"task_{task_id}")

    @staticmethod
    def open_folder(folder: str):
        """打开文件浏览器"""
        import os
        import sys
        import subprocess

        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
