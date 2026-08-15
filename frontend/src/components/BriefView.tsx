import type { TalkingPointsBrief } from "../types";

export default function BriefView({ brief }: { brief: TalkingPointsBrief }) {
  return (
    <article className="brief">
      <section className="brief-section">
        <h2>Event</h2>
        <p>{brief.event_summary}</p>
      </section>

      <section className="brief-section">
        <h2>Framing</h2>
        <p>{brief.framing}</p>
      </section>

      <section className="brief-section">
        <h2>Talking points</h2>
        <ol className="point-list">
          {brief.points.map((point, i) => (
            <li key={i} className="point">
              <h3>{point.headline}</h3>
              <p>{point.talking_point}</p>

              {point.corpus_support.length > 0 && (
                <div className="citations">
                  <h4>From her own remarks</h4>
                  {point.corpus_support.map((c, j) => (
                    <blockquote key={j} className="corpus-citation">
                      <p>&ldquo;{c.quote}&rdquo;</p>
                      <cite>
                        <a href={c.source_url} target="_blank" rel="noopener noreferrer">
                          {c.title}
                        </a>
                        {c.date && <span className="citation-date"> &middot; {c.date}</span>}
                      </cite>
                    </blockquote>
                  ))}
                </div>
              )}

              {point.web_context.length > 0 && (
                <div className="citations">
                  <h4>Current context</h4>
                  <ul className="web-citations">
                    {point.web_context.map((c, j) => (
                      <li key={j}>
                        {c.claim}{" "}
                        <a href={c.url} target="_blank" rel="noopener noreferrer">
                          {c.title}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </li>
          ))}
        </ol>
      </section>

      {brief.likely_questions.length > 0 && (
        <section className="brief-section">
          <h2>Likely questions</h2>
          <ul className="question-list">
            {brief.likely_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </section>
      )}

      {brief.gaps.length > 0 && (
        <section className="brief-section brief-gaps">
          <h2>Gaps in the corpus</h2>
          <p className="gaps-note">
            The corpus held no relevant prior remarks on these, so nothing below is
            backed by something she has already said.
          </p>
          <ul>
            {brief.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
