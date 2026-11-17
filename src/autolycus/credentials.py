"""Windows DPAPI, current-user scope. No plaintext credentials on disk."""
import getpass
import json
import os
from pathlib import Path

NAMES = ("AUTOLYCUS_ACCESS_TOKEN", "AUTOLYCUS_USER_ID", "AUTOLYCUS_FEISHU_WEBHOOK", "AUTOLYCUS_FEISHU_SECRET")


def protect(data, decrypt=False):
    if os.name != "nt":
        raise ValueError("加密凭据目前只支持 Windows，请在其他平台使用环境变量")
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ValueError("Windows 凭据加解密失败，请使用保存凭据时的 Windows 账号")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def save_credentials(path, values):
    if not values.get(NAMES[0]) or not values.get(NAMES[2]):
        raise ValueError("后台系统访问令牌和飞书 Webhook 不能为空")
    encrypted = protect(json.dumps({name: values.get(name, "") for name in NAMES}).encode())
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(path)


def read_credentials(path):
    try:
        result = json.loads(protect(Path(path).read_bytes(), decrypt=True))
    except (OSError, ValueError, UnicodeError):
        raise ValueError("加密凭据读取失败，请用当前 Windows 用户重新初始化凭据") from None
    if not isinstance(result, dict) or any(not isinstance(result.get(name), str) for name in NAMES):
        raise ValueError("凭据文件格式无效，请重新初始化")
    return result


def load_credentials(path):
    if os.name == "nt" and Path(path).exists():
        for name, value in read_credentials(path).items():
            # Explicit environment variables take precedence, including empty ones.
            if name not in os.environ and value:
                os.environ[name] = value


def initialize(path, from_environment=False):
    if from_environment:
        values = {name: os.environ.get(name, "").strip() for name in NAMES}
    else:
        prompts = ["管理员系统访问令牌", "管理员用户ID（无则回车）", "飞书Webhook", "飞书签名密钥（未启用则回车）"]
        values = {name: getpass.getpass(f"{prompt}：").strip() for name, prompt in zip(NAMES, prompts)}
    save_credentials(path, values)
    print("凭据已使用当前 Windows 用户加密保存；未显示或记录密钥。")
