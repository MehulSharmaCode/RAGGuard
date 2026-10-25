/**
 * Turns the backend answer string into paragraphs and lists for display.
 *
 * Citation markers: the backend labels the evidence it supplied as S1..Sn and
 * the model references them as "[S1]". A marker becomes interactive only when
 * that ID exists in the response's `sources`; anything else stays plain text.
 * Consecutive markers ("[S1][S2]", "[S1], [S2]") form one citation group, rendered as
 * "[S1, S2]", so adjacent labels never run together as "S1S2" on screen or when copied.
 * The UI never creates citations of its own.
 */

export type Segment =
  | { type: "text"; text: string }
  | { type: "strong"; text: string }
  | { type: "cite"; sourceIds: string[] };

export type Block =
  | { type: "paragraph"; segments: Segment[]; interpretation: boolean }
  | { type: "list"; ordered: boolean; items: Segment[][] };

const TOKEN = /\[(S\d+)\]|\*\*(.+?)\*\*/g;
// Only whitespace or a comma may separate two markers of the same group.
const GROUP_GAP = /^[\s,]*$/;
const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;
const INTERPRETATION = /^Interpretation:\s*/i;

export function parseSegments(text: string, sourceIds: ReadonlySet<string>): Segment[] {
  const segments: Segment[] = [];
  const pushText = (value: string) => {
    const previous = segments.at(-1);
    if (previous?.type === "text") previous.text += value;
    else segments.push({ type: "text", text: value });
  };
  let last = 0;
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0;
    if (match[1] !== undefined) {
      if (sourceIds.has(match[1])) {
        const previous = segments.at(-1);
        const gap = text.slice(last, index);
        if (previous?.type === "cite" && GROUP_GAP.test(gap)) {
          if (!previous.sourceIds.includes(match[1])) previous.sourceIds.push(match[1]);
        } else {
          if (index > last) pushText(gap);
          segments.push({ type: "cite", sourceIds: [match[1]] });
        }
      } else {
        if (index > last) pushText(text.slice(last, index));
        pushText(match[0]);
      }
    } else {
      if (index > last) pushText(text.slice(last, index));
      segments.push({ type: "strong", text: match[2] ?? "" });
    }
    last = index + match[0].length;
  }
  if (last < text.length) pushText(text.slice(last));
  return segments;
}

export function parseAnswer(answer: string, sourceIds: ReadonlySet<string>): Block[] {
  // The prompt asks the model to start interpretation sentences with "Interpretation:";
  // give each one its own paragraph so it can be set apart from stated facts.
  const normalized = answer.replace(/\r\n?/g, "\n").replace(/[ \t]+(Interpretation:)/g, "\n\n$1");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(" ").trim();
    paragraph = [];
    if (!text) return;
    const interpretation = INTERPRETATION.test(text);
    blocks.push({
      type: "paragraph",
      interpretation,
      segments: parseSegments(interpretation ? text.replace(INTERPRETATION, "") : text, sourceIds),
    });
  };
  const flushList = () => {
    if (!list) return;
    blocks.push({
      type: "list",
      ordered: list.ordered,
      items: list.items.map((item) => parseSegments(item, sourceIds)),
    });
    list = null;
  };

  for (const line of normalized.split("\n")) {
    const ordered = NUMBERED.test(line);
    if (ordered || BULLET.test(line)) {
      flushParagraph();
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push(line.replace(ordered ? NUMBERED : BULLET, "").trim());
    } else if (line.trim() === "") {
      flushParagraph();
      flushList();
    } else if (list && /^\s{2,}/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
