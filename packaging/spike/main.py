"""二期④打包 spike:PyWebView 壳最小验照(窗口加载后端服务地址)。

验照问题:①PyWebView+Nuitka 工具链在本机可否出 exe;②体积是否落在 30-50MB
目标带;③窗口能否打开页面。后端整体打包(uvicorn+数据文件)为下一步,不在本 spike。
"""
import webview

if __name__ == "__main__":
    webview.create_window("Soulspring spike", "http://127.0.0.1:8600/", width=1100, height=720)
    webview.start()
