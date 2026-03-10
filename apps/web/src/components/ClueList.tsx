import type { PuzzleEntry } from "../api/puzzles";

function getEnumeration(entry: PuzzleEntry): string {
  const explicitEnumeration = entry.enumeration?.trim();
  if (explicitEnumeration) return explicitEnumeration;

  const parts = entry.answer
    .trim()
    .split(/[^A-Za-z0-9]+/)
    .map((part) => part.trim())
    .filter(Boolean);

  if (parts.length > 1) {
    return parts.map((part) => String(part.length)).join(", ");
  }

  return String(entry.length);
}

export default function ClueList({
  entries,
  activeEntryId,
  checkedEntryIds,
  onSelectEntry,
}: {
  entries: PuzzleEntry[];
  activeEntryId: string | null;
  checkedEntryIds: string[];
  onSelectEntry?: (entryId: string, direction: "across" | "down") => void;
}) {
  const across = entries.filter((e) => e.direction === "across");
  const down = entries.filter((e) => e.direction === "down");
  const checked = new Set(checkedEntryIds);
  const getItemClassName = (entryId: string) => {
    const classes = ["clue-item"];
    if (entryId === activeEntryId) classes.push("is-active");
    if (checked.has(entryId)) classes.push("is-checked");
    return classes.join(" ");
  };

  return (
    <div className="clue-list">
      <section className="card" aria-labelledby="across-clues-heading">
        <h3 id="across-clues-heading">Across</h3>
        <ul aria-label="Across clues">
          {across.map((entry) => (
            <li key={entry.id} className={getItemClassName(entry.id)}>
              <button
                type="button"
                className="clue-item__button"
                onClick={() => onSelectEntry?.(entry.id, entry.direction)}
                aria-pressed={entry.id === activeEntryId}
              >
                <span className="clue-item__main">
                  <strong>{entry.number}.</strong> {entry.clue} ({getEnumeration(entry)})
                </span>
              </button>
              {checked.has(entry.id) ? (
                <span className="clue-item__tick" aria-label="Checked correct" title="Checked correct">
                  {"\u2713"}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
      <section className="card" aria-labelledby="down-clues-heading">
        <h3 id="down-clues-heading">Down</h3>
        <ul aria-label="Down clues">
          {down.map((entry) => (
            <li key={entry.id} className={getItemClassName(entry.id)}>
              <button
                type="button"
                className="clue-item__button"
                onClick={() => onSelectEntry?.(entry.id, entry.direction)}
                aria-pressed={entry.id === activeEntryId}
              >
                <span className="clue-item__main">
                  <strong>{entry.number}.</strong> {entry.clue} ({getEnumeration(entry)})
                </span>
              </button>
              {checked.has(entry.id) ? (
                <span className="clue-item__tick" aria-label="Checked correct" title="Checked correct">
                  {"\u2713"}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
