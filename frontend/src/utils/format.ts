export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const rtf = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  if (diff < 60_000) return rtf.format(-Math.round(diff / 1000), "second");
  if (diff < 3_600_000) return rtf.format(-Math.round(diff / 60_000), "minute");
  if (diff < 86_400_000) return rtf.format(-Math.round(diff / 3_600_000), "hour");
  return rtf.format(-Math.round(diff / 86_400_000), "day");
}
