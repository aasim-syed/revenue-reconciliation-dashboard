import * as React from "react";
import { Check, X } from "lucide-react";
import type { User } from "../lib/types";
import { api } from "../lib/api";
import { HeroButton } from "./hero-button";

const Spline = React.lazy(() => import("@splinetool/react-spline"));

type View = "login" | "signup";

const PASSWORD_RULES: { label: string; test: (value: string) => boolean }[] = [
  { label: "At least 8 characters", test: (v) => v.length >= 8 },
  { label: "Upper & lowercase letters", test: (v) => /[a-z]/.test(v) && /[A-Z]/.test(v) },
  { label: "At least one number", test: (v) => /[0-9]/.test(v) },
  { label: "At least one symbol", test: (v) => /[^A-Za-z0-9]/.test(v) },
];

const STRENGTH_LEVELS = [
  { label: "Weak", barClass: "bg-destructive", textClass: "text-destructive" },
  { label: "Fair", barClass: "bg-amber-500", textClass: "text-amber-500" },
  { label: "Good", barClass: "bg-sky-400", textClass: "text-sky-400" },
  { label: "Strong", barClass: "bg-primary", textClass: "text-primary" },
];

function PasswordStrength({ password }: { password: string }) {
  const passed = PASSWORD_RULES.filter((rule) => rule.test(password)).length;
  const level = STRENGTH_LEVELS[Math.max(0, passed - 1)];

  return (
    <div className="mb-4 -mt-2 grid gap-2">
      <div className="grid grid-cols-4 gap-1">
        {PASSWORD_RULES.map((_, i) => (
          <span
            key={i}
            className={`h-1 rounded-full transition-colors ${i < passed ? level.barClass : "bg-border"}`}
          />
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className={`text-xs font-medium ${level.textClass}`}>{level.label}</span>
      </div>
      <ul className="grid grid-cols-2 gap-x-3 gap-y-1">
        {PASSWORD_RULES.map((rule) => {
          const ok = rule.test(password);
          return (
            <li
              key={rule.label}
              className={`flex items-center gap-1.5 text-[11px] transition-colors ${ok ? "text-foreground" : "text-muted-foreground"}`}
            >
              {ok ? (
                <Check className="size-3 text-primary shrink-0" />
              ) : (
                <X className="size-3 text-muted-foreground/50 shrink-0" />
              )}
              {rule.label}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Navbar({ view, setView }: { view: View; setView: (v: View) => void }) {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 flex justify-between items-center px-8 lg:px-16 py-5">
      <span className="text-foreground text-xl font-semibold tracking-tight">REVENUE AUDIT</span>
      <HeroButton
        variant="navCta"
        size="lg"
        className="hidden md:inline-flex"
        onClick={() => setView(view === "login" ? "signup" : "login")}
      >
        {view === "login" ? "Sign Up" : "Log In"}
      </HeroButton>
    </nav>
  );
}

export function HeroAuthScreen({ onAuthed }: { onAuthed: (user: User) => void }) {
  const [view, setView] = React.useState<View>("login");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = view === "login" ? await api.login(email, password) : await api.signup(email, password);
      onAuthed(result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="hero-scope font-sora antialiased">
      <Navbar view={view} setView={setView} />
      <section className="relative min-h-screen flex items-center bg-hero-bg overflow-hidden">
        <div className="absolute inset-0">
          <React.Suspense fallback={<div className="absolute inset-0 bg-hero-bg" />}>
            <Spline scene="https://prod.spline.design/Slk6b8kz3LRlKiyk/scene.splinecode" className="w-full h-full" />
          </React.Suspense>
        </div>
        <div className="absolute inset-0 bg-black/30 z-[1] pointer-events-none" />

        <div className="relative z-10 w-full h-full flex flex-col lg:flex-row items-center justify-between gap-10 px-6 md:px-10 lg:px-16 pt-28 pb-10">
          <div className="pointer-events-none w-full max-w-2xl">
            <h1
              className="opacity-0 animate-fade-up text-[clamp(2.25rem,6vw,4.5rem)] font-bold leading-[1.05] tracking-[-0.05em] text-foreground mb-2 md:mb-4 uppercase"
              style={{ animationDelay: "0.2s" }}
            >
              REVENUE<span className="text-primary"> AUDIT</span>
            </h1>
            <p
              className="opacity-0 animate-fade-up text-foreground/80 text-[clamp(1.125rem,2.5vw,1.875rem)] font-light mb-3 md:mb-6"
              style={{ animationDelay: "0.4s" }}
            >
              We reconcile revenue correctly.
            </p>
            <p
              className="opacity-0 animate-fade-up text-muted-foreground text-[clamp(0.875rem,1.5vw,1.25rem)] font-light mb-4 md:mb-8 max-w-xl"
              style={{ animationDelay: "0.55s" }}
            >
              Upload order and payment exports, reconcile mismatches, and focus the review on the records that
              actually put money at risk.
            </p>
            <p
              className="opacity-0 animate-fade-up text-muted-foreground/60 text-xs font-light"
              style={{ animationDelay: "0.85s" }}
            >
              Deterministic matching. Per-user imports. Backend-only LLM summaries.
            </p>
          </div>

          <form
            onSubmit={submit}
            className="pointer-events-auto opacity-0 animate-fade-up w-full max-w-sm shrink-0 bg-secondary/70 border border-border rounded-lg p-6 backdrop-blur-md lg:mr-4"
            style={{ animationDelay: "0.7s" }}
          >
            <div className="grid grid-cols-2 gap-1 bg-background/60 border border-border rounded-md p-1 mb-4">
              <button
                type="button"
                onClick={() => setView("login")}
                className={`rounded-sm py-2 text-xs uppercase tracking-widest transition-colors ${view === "login" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
              >
                Log in
              </button>
              <button
                type="button"
                onClick={() => setView("signup")}
                className={`rounded-sm py-2 text-xs uppercase tracking-widest transition-colors ${view === "signup" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
              >
                Sign up
              </button>
            </div>
            <label className="grid gap-1.5 mb-3">
              <span className="text-xs uppercase tracking-widest text-muted-foreground">Email</span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="bg-background border border-border rounded-md px-4 py-2.5 text-foreground text-sm outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            <label className="grid gap-1.5 mb-3">
              <span className="text-xs uppercase tracking-widest text-muted-foreground">Password</span>
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="bg-background border border-border rounded-md px-4 py-2.5 text-foreground text-sm outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            {view === "signup" && password.length > 0 && <PasswordStrength password={password} />}
            {error && <p className="text-destructive text-xs mb-3">{error}</p>}
            <HeroButton type="submit" variant="hero" disabled={loading} className="w-full font-bold">
              {loading ? "Please wait" : view === "login" ? "Log In" : "Create Account"}
            </HeroButton>
          </form>
        </div>
      </section>
    </div>
  );
}
