import type { Transition, Variants } from "framer-motion";

export const messageVariants: Variants = {
  hidden: { opacity: 0, y: 8, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.25, ease: "easeOut" },
  },
};

export const sidebarVariants: Variants = {
  hidden: { x: -240, opacity: 0 },
  visible: {
    x: 0,
    opacity: 1,
    transition: { duration: 0.3, ease: "easeOut" },
  },
};

export const heroVariants: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: "easeOut", delay: 0.1 },
  },
};

export const wizardStepVariants: Variants = {
  hidden: { opacity: 0, x: 28 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.35, ease: "easeOut" },
  },
  exit: {
    opacity: 0,
    x: -28,
    transition: { duration: 0.25, ease: "easeIn" },
  },
};

export const panelSlideVariants: Variants = {
  hidden: { x: 360, opacity: 0 },
  visible: {
    x: 0,
    opacity: 1,
    transition: { duration: 0.3, ease: "easeOut" },
  },
  exit: {
    x: 360,
    opacity: 0,
    transition: { duration: 0.2, ease: "easeIn" },
  },
};

export const modalVariants: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.22, ease: "easeOut" },
  },
  exit: {
    opacity: 0,
    scale: 0.96,
    transition: { duration: 0.16, ease: "easeIn" },
  },
};

export const nodePulseTransition: Transition = {
  duration: 1.4,
  repeat: Infinity,
  ease: "easeInOut",
};

export const warningGlowVariants: Variants = {
  pulse: {
    scale: [1, 1.04, 1],
    transition: { duration: 1.6, repeat: Infinity, ease: "easeInOut" },
  },
};

export const snapshotEnter: Variants = {
  hidden: { opacity: 0, scale: 0.6 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.3, ease: "easeOut" },
  },
};
