const DEFAULT_APP_TIMEZONE = "Europe/London";

export function todayIsoInTimezone(timeZone: string = DEFAULT_APP_TIMEZONE) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(new Date());
}
