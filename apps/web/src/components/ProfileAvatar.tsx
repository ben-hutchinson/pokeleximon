const PRESET_CLASS_BY_ID: Record<string, string> = {
  sky: "is-sky",
  cream: "is-cream",
  blush: "is-blush",
  plum: "is-plum",
};

export type AvatarPresetOption = {
  id: "sky" | "cream" | "blush" | "plum";
  label: string;
};

export const AVATAR_PRESETS: AvatarPresetOption[] = [
  { id: "sky", label: "Sky" },
  { id: "cream", label: "Cream" },
  { id: "blush", label: "Blush" },
  { id: "plum", label: "Plum" },
];

function deriveInitials(displayName: string) {
  const tokens = displayName
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  if (tokens.length === 0) return "PL";
  return tokens.map((token) => token[0]?.toUpperCase() ?? "").join("") || "PL";
}

export default function ProfileAvatar({
  avatarPreset,
  className = "",
  displayName,
  size = "md",
}: {
  avatarPreset?: string | null;
  className?: string;
  displayName: string;
  size?: "sm" | "md" | "lg";
}) {
  const presetClass = avatarPreset ? PRESET_CLASS_BY_ID[avatarPreset] ?? "is-custom" : "is-initials";
  const initials = deriveInitials(displayName);
  return (
    <span className={`profile-avatar profile-avatar--${size} ${presetClass} ${className}`.trim()} aria-hidden="true">
      <span className="profile-avatar__inner">{initials}</span>
    </span>
  );
}
