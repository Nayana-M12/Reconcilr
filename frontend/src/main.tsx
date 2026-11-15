import { Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Application rendering error", error, errorInfo);
  }

  render() {
    if (this.state.error) {
      return <div className="flex min-h-screen items-center justify-center p-6 text-red-200"><div><h1 className="text-xl font-semibold">Something went wrong</h1><p className="mt-2">{this.state.error.message}</p></div></div>;
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
