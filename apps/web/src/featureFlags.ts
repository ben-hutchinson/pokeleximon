function parseBooleanEnvFlag(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

export const FEATURE_CONNECTIONS_ENABLED = parseBooleanEnvFlag(import.meta.env.VITE_FEATURE_CONNECTIONS_ENABLED);
