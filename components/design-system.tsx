import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost";

export function AGLogo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] shadow-[0_0_24px_oklch(0.68_0.19_255_/_0.12)]">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M8 1.5L14.5 5.25V10.75L8 14.5L1.5 10.75V5.25L8 1.5Z"
            stroke="var(--ag-blue)"
            strokeWidth="1.2"
            strokeLinejoin="round"
          />
          {!compact && <circle cx="8" cy="8" r="2.5" fill="var(--ag-blue)" opacity="0.72" />}
        </svg>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[15px] font-semibold tracking-[-0.02em] text-[var(--ag-text-0)]">
          Antigravity
        </span>
        <span className="rounded-md border border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--ag-blue)]">
          Protocol
        </span>
      </div>
    </div>
  );
}

export function AGButton({
  children,
  href,
  variant = "primary",
  disabled,
  className = "",
  ...props
}: {
  children: ReactNode;
  href?: string;
  variant?: ButtonVariant;
  disabled?: boolean;
  className?: string;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children">) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold transition-all duration-200";
  const variants: Record<ButtonVariant, string> = {
    primary:
      "bg-[oklch(0.96_0.004_265)] text-[oklch(0.09_0.012_265)] shadow-[0_0_40px_oklch(0.95_0.005_260_/_0.1)] hover:-translate-y-0.5 hover:bg-white disabled:bg-[var(--ag-surface-1)] disabled:text-[var(--ag-text-3)]",
    secondary:
      "border border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-0)] hover:border-[var(--ag-border-strong)] hover:bg-[var(--ag-surface-1)] disabled:text-[var(--ag-text-3)]",
    ghost:
      "border border-transparent bg-transparent text-[var(--ag-text-2)] hover:border-[var(--ag-border)] hover:bg-[var(--ag-surface-0)] hover:text-[var(--ag-text-0)] disabled:text-[var(--ag-text-3)]",
  };

  if (href) {
    return (
      <Link href={href} className={`${base} ${variants[variant]} ${className}`}>
        {children}
      </Link>
    );
  }

  return (
    <button
      {...props}
      disabled={disabled}
      className={`${base} ${variants[variant]} disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
    >
      {children}
    </button>
  );
}

export function AGChip({
  children,
  active = false,
  className = "",
}: {
  children: ReactNode;
  active?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-lg border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${
        active
          ? "border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] text-[var(--ag-blue)]"
          : "border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-2)]"
      } ${className}`}
    >
      {children}
    </span>
  );
}

export function AGSurface({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`ag-card rounded-2xl ${className}`}>{children}</div>;
}

export function AGSectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--ag-text-3)]">
      {children}
    </p>
  );
}

export function AGMetricCard({
  label,
  value,
  subtext,
  emphasis = "default",
}: {
  label: string;
  value: ReactNode;
  subtext?: string;
  emphasis?: "default" | "blue" | "green" | "amber" | "red";
}) {
  const emphasisClass =
    emphasis === "blue"
      ? "text-[var(--ag-blue)]"
      : emphasis === "green"
      ? "text-[var(--ag-green)]"
      : emphasis === "amber"
      ? "text-[var(--ag-amber)]"
      : emphasis === "red"
      ? "text-[var(--ag-red)]"
      : "text-[var(--ag-text-0)]";

  return (
    <AGSurface className="px-5 py-5">
      <AGSectionLabel>{label}</AGSectionLabel>
      <p className={`mt-2 font-mono text-3xl font-semibold tracking-[-0.05em] ${emphasisClass}`}>{value}</p>
      {subtext && <p className="mt-2 text-xs text-[var(--ag-text-3)]">{subtext}</p>}
    </AGSurface>
  );
}

export function AGVerdictBadge({
  verdict,
  size = "md",
}: {
  verdict: string | null | undefined;
  size?: "md" | "lg";
}) {
  const key = verdict ?? "N/A";
  const palette =
    key === "HIRE"
      ? "border-[oklch(0.76_0.16_155_/_0.28)] bg-[oklch(0.76_0.16_155_/_0.1)] text-[var(--ag-green)]"
      : key === "MAYBE"
      ? "border-[oklch(0.8_0.16_72_/_0.28)] bg-[oklch(0.8_0.16_72_/_0.1)] text-[var(--ag-amber)]"
      : key === "NO HIRE"
      ? "border-[oklch(0.66_0.21_24_/_0.28)] bg-[oklch(0.66_0.21_24_/_0.1)] text-[var(--ag-red)]"
      : key === "INSUFFICIENT_DATA"
      ? "border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] text-[var(--ag-blue)]"
      : "border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-2)]";

  return (
    <span
      className={`inline-flex items-center rounded-xl border font-semibold uppercase tracking-[0.14em] ${palette} ${
        size === "lg" ? "px-4 py-2 text-xs" : "px-3 py-1.5 text-[10px]"
      }`}
    >
      {key}
    </span>
  );
}

export function AGScoreGauge({
  score,
  max = 10,
  size = 144,
  label = "overall",
}: {
  score: number | null | undefined;
  max?: number;
  size?: number;
  label?: string;
}) {
  const safeScore = typeof score === "number" && Number.isFinite(score) ? score : 0;
  const radius = size / 2 - 10;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.max(0, Math.min(1, safeScore / max));
  const strokeDasharray = `${progress * circumference} ${circumference}`;
  const stroke =
    progress >= 0.7
      ? "var(--ag-green)"
      : progress >= 0.4
      ? "var(--ag-amber)"
      : "var(--ag-red)";

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="oklch(0.18 0.015 265)" strokeWidth="8" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={stroke}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={strokeDasharray}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ filter: `drop-shadow(0 0 12px ${stroke})` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-3xl font-semibold tracking-[-0.05em] text-[var(--ag-text-0)]">
          {typeof score === "number" && Number.isFinite(score) ? score.toFixed(1) : "—"}
        </span>
        <span className="mt-1 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
          {label}
        </span>
      </div>
    </div>
  );
}

export function AGScoreBar({
  label,
  score,
  max = 10,
}: {
  label: string;
  score: number;
  max?: number;
}) {
  const pct = Math.max(0, Math.min(100, (score / max) * 100));
  const barColor = score >= 7 ? "var(--ag-green)" : score >= 4 ? "var(--ag-amber)" : "var(--ag-red)";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="capitalize text-[var(--ag-text-1)]">{label.replace(/_/g, " ")}</span>
        <span className="font-mono text-xs text-[var(--ag-text-3)]">{score}/{max}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[var(--ag-surface-2)]">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: barColor, boxShadow: `0 0 12px ${barColor}` }}
        />
      </div>
    </div>
  );
}

export function AGSprintDivider({ sprint, label }: { sprint: number; label: string }) {
  return (
    <div className="flex items-center gap-4 py-2">
      <div className="h-px flex-1 bg-[var(--ag-border)]" />
      <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-[var(--ag-blue)]">
        Sprint {sprint} — {label}
      </span>
      <div className="h-px flex-1 bg-[var(--ag-border)]" />
    </div>
  );
}

export function AGSeverityPip({ severity }: { severity: string }) {
  const color =
    severity === "high"
      ? "bg-[var(--ag-red)]"
      : severity === "medium"
      ? "bg-[var(--ag-amber)]"
      : "bg-[var(--ag-blue)]";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}
