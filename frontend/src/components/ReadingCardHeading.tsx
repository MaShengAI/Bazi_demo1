/** Shared paper-card heading for locked previews and personal readings. */
export function ReadingCardHeading({ title, index, id, focusable = false }: {
  title: string;
  index: number;
  id?: string;
  focusable?: boolean;
}) {
  return <header className="reading-card-heading">
    <span className="preview-topic-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
    {focusable ? <h4 id={id} tabIndex={-1}>{title}</h4> : <h3 id={id}>{title}</h3>}
    <div className="preview-title-ornament" aria-hidden="true"><span />❀<span /></div>
  </header>;
}
