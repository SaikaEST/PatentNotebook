"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { login, register } from "../lib/api";
import { RESETTABLE_WORKSPACE_KEYS, TOKEN_STORAGE_KEY } from "../lib/workspace";

type AuthMode = "login" | "register";

function toMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    const normalized = error.message.trim();
    if (normalized === "User not found") return "用户不存在。";
    if (normalized === "Invalid credentials") return "邮箱或密码错误。";
    if (normalized === "User already exists") return "用户已存在。";
    return error.message;
  }
  return fallback;
}

export default function Home() {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const clearWorkspaceState = () => {
    RESETTABLE_WORKSPACE_KEYS.forEach((key) => {
      localStorage.removeItem(key);
      sessionStorage.removeItem(key);
    });
  };

  const handleAuth = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email.trim()) {
      setErrorMessage("请输入邮箱。");
      return;
    }
    if (!password) {
      setErrorMessage("请输入密码。");
      return;
    }
    if (mode === "register" && password !== confirmPassword) {
      setErrorMessage("两次输入的密码不一致。");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      const result =
        mode === "register"
          ? await register(email.trim(), password)
          : await login(email.trim(), password);
      clearWorkspaceState();
      localStorage.setItem(TOKEN_STORAGE_KEY, result.access_token);
      setPassword("");
      setConfirmPassword("");
      setSuccessMessage(mode === "register" ? "注册成功。" : "登录成功。");
      router.push("/assistant");
    } catch (error) {
      setErrorMessage(toMessage(error, mode === "register" ? "注册失败。" : "登录失败。"));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card">
        <h1>专利审查助手</h1>
        <p className="auth-subtitle">请先注册或登录</p>

        <div className="auth-tabs">
          <button
            type="button"
            className={mode === "login" ? "active" : ""}
            onClick={() => {
              setMode("login");
              setErrorMessage("");
              setSuccessMessage("");
            }}
          >
            登录
          </button>
          <button
            type="button"
            className={mode === "register" ? "active" : ""}
            onClick={() => {
              setMode("register");
              setErrorMessage("");
              setSuccessMessage("");
            }}
          >
            注册
          </button>
        </div>

        <form className="auth-form" onSubmit={handleAuth}>
          <label className="field-group">
            <span>邮箱</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="请输入邮箱"
            />
          </label>
          <label className="field-group">
            <span>密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
            />
          </label>
          {mode === "register" ? (
            <label className="field-group">
              <span>确认密码</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="请再次输入密码"
              />
            </label>
          ) : null}

          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "提交中..." : mode === "register" ? "注册并登录" : "登录"}
          </button>
        </form>

        {errorMessage ? <p className="panel-message error">{errorMessage}</p> : null}
        {successMessage ? <p className="panel-message success">{successMessage}</p> : null}
      </section>
    </main>
  );
}
