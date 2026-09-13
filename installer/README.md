# 星弦 安装包（含虚拟摄像头）

安装包会把「星弦虚拟摄像头」随应用一起装到系统里，装完后在**直播伴侣 / OBS / 浏览器**
的摄像头列表里就能直接选到该设备，不需要用户单独装 OBS 或手动配置。

## 原理

- **虚拟摄像头驱动**：随包内置 [`UnityCapture`](https://github.com/schellingb/UnityCapture)
  的 DirectShow 过滤器（`UnityCaptureFilter32.dll` / `UnityCaptureFilter64.dll`，MIT 许可），
  安装时用 `regsvr32` 注册，并指定设备名为 **星弦虚拟摄像头**。
- **应用推流**：客户端用 `pyvirtualcam` 的 `unitycapture` 后端，把虚拟形象画面
  （Live2D / VRM）以 30FPS 推送到该摄像头设备。

## 打包步骤

1. 安装客户端依赖（含 `pyvirtualcam`）：

   ```powershell
   cd client-python
   .\.venv\Scripts\pip install -r requirements.txt
   .\.venv\Scripts\pip install pyinstaller
   ```

2. 用 PyInstaller 打包客户端：

   ```powershell
   .\.venv\Scripts\pyinstaller --noconfirm --windowed --name 星弦 ^
       --add-data "app/resources;app/resources" start.py
   ```

   产物目录：`client-python\dist\星弦\`

3. 安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)，编译安装脚本：

   ```powershell
   iscc installer\star_string.iss
   ```

   产物：`installer\output\星弦安装包.exe`

## 安装后的效果

- 安装过程会自动注册虚拟摄像头（需要管理员权限，安装包已声明 `PrivilegesRequired=admin`）。
- 打开直播伴侣 → 添加「摄像头」来源 → 设备列表里选择 **星弦虚拟摄像头**。
- 客户端首页「直播输出（虚拟摄像头）」点「启动虚拟摄像头」即可输出画面。
- 卸载星弦时，安装包会自动注销该虚拟摄像头。

## 修复

如果设备列表里没有「星弦虚拟摄像头」，可在客户端首页点「安装/修复驱动」重新注册
（会弹出管理员权限确认）。

## 许可

- `UnityCaptureFilter*.dll` 来自 UnityCapture，过滤器部分为 MIT 许可，
  随包保留了 `UnityCapture-README.md`。
