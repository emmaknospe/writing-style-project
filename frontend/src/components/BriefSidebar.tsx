import type { Brief } from "../types";

/** The drafted brief. Every citation shown here has already been verified
 *  server-side against the corpus chunk it names. */
export default function BriefSidebar({ brief }: { brief: Brief }) {
  return (
    <div className="sidebar-inner">
      <h2>Brief</h2>

      {brief.framing && (
        <section className="brief-block">
          <h3>Framing</h3>
          <p>{brief.framing}</p>
        </section>
      )}

      <ol className="points">
        {brief.points.map((point) => (
          <li key={point.id} className="point">
            <h3>{point.heading}</h3>
            <p className="point-text">{point.text}</p>

            {point.sources.length > 0 && (
              <div className="citations">
                <h4>From her own remarks</h4>
                {point.sources.map((s) => (
                  <blockquote key={s.id} className="corpus-citation">
                    <p>&ldquo;{s.quoted_text}&rdquo;</p>
                    <cite>
                      {s.source_url ? (
                        <a href={s.source_url} target="_blank" rel="noopener noreferrer">
                          {s.title}
                        </a>
                      ) : (
                        s.title
                      )}
                      {s.date && <span className="citation-date"> &middot; {s.date}</span>}
                    </cite>
                  </blockquote>
                ))}
              </div>
            )}

            {point.web_sources.length > 0 && (
              <div className="citations">
                <h4>Current context</h4>
                <ul className="web-citations">
                  {point.web_sources.map((w) => (
                    <li key={w.id}>
                      {w.claim}{" "}
                      <a href={w.url} target="_blank" rel="noopener noreferrer">
                        {w.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ol>

      {brief.likely_questions.length > 0 && (
        <section className="brief-block">
          <h3>Likely questions</h3>
          <ul>
            {brief.likely_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </section>
      )}

      {brief.gaps.length > 0 && (
        <section className="brief-block sidebar-gaps">
          <h3>Gaps in the corpus</h3>
          <ul>
            {brief.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
