import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import licensing


def _generator_config():
    """登录凭据只存在于生成器目录的 gen_config.json，不随客户端分发。"""
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    try:
        return json.loads((base / "gen_config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


class LicenseGeneratorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("授权码生成器")
        self.root.geometry("720x560")
        self.root.resizable(False, False)

        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.machine_id = tk.StringVar()
        self.license_type = tk.StringVar(value=licensing.LICENSE_TYPE_TERM)
        self.license_code = tk.StringVar()
        self.is_logged_in = False

        self.build_login()

    def clear(self):
        for item in self.root.winfo_children():
            item.destroy()

    def build_login(self):
        self.clear()
        frame = tk.Frame(self.root, padx=28, pady=28)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="授权码生成器", font=("Microsoft YaHei UI", 22, "bold")).pack(anchor="w")
        tk.Label(frame, text="仅授权管理员使用。", fg="#526a7e").pack(anchor="w", pady=(8, 24))

        tk.Label(frame, text="账号").pack(anchor="w")
        tk.Entry(frame, textvariable=self.username, font=("Microsoft YaHei UI", 12)).pack(fill="x", pady=(6, 14))
        tk.Label(frame, text="密码").pack(anchor="w")
        tk.Entry(frame, textvariable=self.password, font=("Microsoft YaHei UI", 12), show="*").pack(fill="x", pady=(6, 20))
        tk.Button(frame, text="登录", height=2, bg="#116fa6", fg="#ffffff", command=self.login).pack(fill="x")
        self.root.bind("<Return>", lambda _event: self.login())

    def login(self):
        cfg = _generator_config()
        cfg_user = str(cfg.get("username") or "").strip()
        cfg_pass = str(cfg.get("password") or "")
        if cfg_user and cfg_pass and self.username.get().strip() == cfg_user and self.password.get() == cfg_pass:
            self.is_logged_in = True
            self.build_generator()
            return
        if not cfg_user or not cfg_pass:
            messagebox.showerror("登录失败", "未配置登录凭据。请在生成器目录创建 gen_config.json（含 username/password）。")
            return
        messagebox.showerror("登录失败", "账号或密码错误。")

    def build_generator(self):
        self.clear()
        frame = tk.Frame(self.root, padx=28, pady=24)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="生成授权码", font=("Microsoft YaHei UI", 22, "bold")).pack(anchor="w")
        tk.Label(frame, text="输入客户安装程序显示的机器 ID，选择授权类型后生成授权码。", fg="#526a7e").pack(anchor="w", pady=(8, 20))

        tk.Label(frame, text="机器 ID").pack(anchor="w")
        tk.Entry(frame, textvariable=self.machine_id, font=("Consolas", 13, "bold")).pack(fill="x", pady=(6, 14))

        tk.Label(frame, text="授权类型").pack(anchor="w")
        type_frame = tk.Frame(frame)
        type_frame.pack(fill="x", pady=(6, 14))
        tk.Radiobutton(
            type_frame,
            text=f"3个月授权（{licensing.LICENSE_VALID_DAYS}天）",
            variable=self.license_type,
            value=licensing.LICENSE_TYPE_TERM,
        ).pack(side="left")
        tk.Radiobutton(
            type_frame,
            text=f"终身授权（{licensing.LIFETIME_LICENSE_PRICE}元）",
            variable=self.license_type,
            value=licensing.LICENSE_TYPE_LIFETIME,
        ).pack(side="left", padx=(24, 0))

        actions = tk.Frame(frame)
        actions.pack(fill="x", pady=(0, 14))
        tk.Button(actions, text="生成授权码", height=2, bg="#116fa6", fg="#ffffff", command=self.generate).pack(side="left", fill="x", expand=True)
        tk.Button(actions, text="清空", height=2, command=self.clear_form).pack(side="left", padx=(10, 0))

        tk.Label(frame, text="授权码").pack(anchor="w")
        self.output = tk.Text(frame, height=8, font=("Consolas", 10), wrap="word")
        self.output.pack(fill="both", expand=True, pady=(6, 12))

        tk.Button(frame, text="复制授权码", height=2, command=self.copy_license).pack(fill="x")

    def generate(self):
        machine = self.machine_id.get().strip().upper()
        if not machine:
            messagebox.showerror("缺少机器 ID", "请输入机器 ID。")
            return
        if not machine.startswith(f"{licensing.APP_CODE}-"):
            if not messagebox.askyesno("机器 ID 格式提醒", "机器 ID 格式看起来不完整，仍要生成吗？"):
                return
        code = licensing.generate_license(machine, license_type=self.license_type.get())
        self.output.delete("1.0", "end")
        self.output.insert("1.0", code)

    def copy_license(self):
        code = self.output.get("1.0", "end").strip()
        if not code:
            messagebox.showinfo("没有授权码", "请先生成授权码。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        messagebox.showinfo("已复制", "授权码已复制。")

    def clear_form(self):
        self.machine_id.set("")
        self.output.delete("1.0", "end")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    LicenseGeneratorApp().run()
