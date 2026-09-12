// 全局错误边界（R9 #6）：渲染/未捕获异常 → 可见横幅，避免白屏"无响应"。
import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  message: string | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { message: null };

  static getDerivedStateFromError(e: unknown): State {
    return { message: e instanceof Error ? e.message : String(e) };
  }

  componentDidCatch(e: unknown) {
    // 保留给控制台排查（R9 #6：请用户下次记录浏览器控制台）
    console.error("[颜回（YanHui）] render error:", e);
  }

  render() {
    if (this.state.message === null) return this.props.children;
    // docs/13 §2：渲染错误若为英文（JS 运行时原生文案）不裸显，给中文人话（原文留控制台）
    const shown = /[\u4e00-\u9fff]/.test(this.state.message)
      ? this.state.message
      : "页面发生未知错误，请刷新重试（详情见浏览器控制台）。";
    return (
      <div className="card error" role="alert">
        <h1>页面渲染出错</h1>
        <p>错误信息：{shown}</p>
        <p className="dim">请记录地址栏 URL 与控制台输出（有助于定位偶发"找不到页面"）。</p>
        <div className="input-row">
          <button className="primary" onClick={() => window.location.reload()}>刷新重试</button>
          <button className="ghost" onClick={() => (window.location.href = "/")}>回仪表盘</button>
        </div>
      </div>
    );
  }
}
