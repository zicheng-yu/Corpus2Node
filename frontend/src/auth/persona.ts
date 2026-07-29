import type { CustomerProfile, ProductPersona } from "../types";

export const DEFAULT_PERSONA: ProductPersona = "operator";

export const FALLBACK_PROFILE: CustomerProfile = {
  schema_version: 1,
  customer_id: "default",
  brand: {
    product_name: "corpus2node",
    tagline: "knowledge graph",
  },
  personas: {
    executive: {
      label: "决策层",
      description: "看总结卡片、评估风险/ROI",
      landing: "/discover?mode=scientific",
      nav: ["discover", "home"],
    },
    researcher: {
      label: "研发",
      description: "看证据链、深度探针、论文对比",
      landing: "/discover?mode=scientific&focus=evidence",
      nav: ["discover", "home"],
    },
    operator: {
      label: "执行",
      description: "上传资料、看笔记、水平测试",
      landing: "/",
      nav: ["home", "new"],
    },
  },
  features: {
    discovery: true,
    notes: true,
    level_test: true,
  },
};

export function coercePersona(value: string | null | undefined): ProductPersona {
  if (value === "executive" || value === "researcher" || value === "operator") return value;
  return DEFAULT_PERSONA;
}

export function homePathFor(persona: ProductPersona | undefined, profile: CustomerProfile): string {
  const key = coercePersona(persona);
  return profile.personas[key]?.landing || FALLBACK_PROFILE.personas[key].landing;
}

export function navFor(persona: ProductPersona | undefined, profile: CustomerProfile) {
  const key = coercePersona(persona);
  return profile.personas[key]?.nav ?? FALLBACK_PROFILE.personas[key].nav;
}
