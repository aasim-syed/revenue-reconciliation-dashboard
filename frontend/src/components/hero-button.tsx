import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../lib/utils";

const heroButtonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-bold cursor-pointer transition-all active:scale-[0.97] disabled:pointer-events-none disabled:opacity-60",
  {
    variants: {
      variant: {
        navCta: "text-foreground bg-nav-button hover:bg-nav-button/80 rounded-lg uppercase text-xs tracking-widest px-6",
        hero: "bg-primary text-primary-foreground rounded-sm hover:brightness-110",
        heroOutline: "bg-white text-background rounded-sm hover:brightness-90",
      },
      size: {
        lg: "h-11",
        heroCta: "px-6 py-3 md:px-8 md:py-4 text-sm",
      },
    },
    defaultVariants: { variant: "hero", size: "heroCta" },
  },
);

export interface HeroButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof heroButtonVariants> {}

export function HeroButton({ className, variant, size, ...props }: HeroButtonProps) {
  return <button className={cn(heroButtonVariants({ variant, size }), className)} {...props} />;
}
