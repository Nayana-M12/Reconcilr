import { ResolutionPlan } from "../api";

type Props = {
  plan: ResolutionPlan;
  selectedSolutionId: string;
  onSelectSolution?: (solutionId: string) => void;
  selectable: boolean;
  committedSolutionId?: string | null;
};

export default function ResolutionPlanView({
  plan,
  selectedSolutionId,
  onSelectSolution,
  selectable,
  committedSolutionId,
}: Props) {
  return (
    <div className="resolution-plan space-y-4">
      <div className="rounded-xl border border-white/10 bg-black/50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-white/45">
            1. Problem identification
          </span>
          <div className="flex flex-wrap gap-1.5">
            <span className="status-badge" data-status={plan.confidence_level}>
              confidence: {plan.confidence_level}
            </span>
            {plan.insufficient_evidence && (
              <span className="status-badge" data-status="unresolved">
                insufficient evidence
              </span>
            )}
          </div>
        </div>
        <p className="mt-2 text-sm text-white/90">{plan.problem_identification}</p>
        {plan.confidence_rationale && (
          <p className="mt-1.5 text-xs text-white/50">{plan.confidence_rationale}</p>
        )}
      </div>

      {plan.possible_causes.length > 0 && (
        <div className="rounded-xl border border-white/10 bg-black/50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-white/45">
            2. Possible causes (hypotheses — not confirmed facts)
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-white/75">
            {plan.possible_causes.map((cause, idx) => (
              <li key={idx}>{cause}</li>
            ))}
          </ul>
        </div>
      )}

      {plan.possible_solutions.length > 0 && (
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-white/45">
              3. Possible solutions {selectable ? "— select one to submit for approval" : ""}
            </p>
          </div>
          <div className="grid gap-3">
            {plan.possible_solutions.map((option, idx) => {
              const isRecommended = plan.recommended_solution_id === option.id;
              const isSelected = (committedSolutionId || selectedSolutionId) === option.id;
              return (
                <div
                  key={option.id}
                  onClick={() => selectable && onSelectSolution?.(option.id)}
                  className={`solution-card rounded-xl border p-4 text-sm ${
                    isSelected ? "solution-card-selected" : "border-white/10 bg-black/50"
                  } ${selectable ? "cursor-pointer" : ""}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {selectable && (
                        <input
                          type="radio"
                          name="resolution_option"
                          checked={selectedSolutionId === option.id}
                          onChange={() => onSelectSolution?.(option.id)}
                          aria-label={option.title}
                        />
                      )}
                      <strong className="text-white">
                        Solution {idx + 1}: {option.title}
                      </strong>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {isRecommended && (
                        <span className="status-badge" data-status="approved">
                          AI recommended
                        </span>
                      )}
                      {committedSolutionId === option.id && (
                        <span className="status-badge" data-status="resolved">
                          selected by analyst
                        </span>
                      )}
                      <span className="status-badge">{option.workflow_action}</span>
                    </div>
                  </div>
                  <div className="mt-2.5 space-y-1.5 text-xs text-white/70">
                    <p>
                      <span className="text-white/45">Possible cause:</span> {option.possible_cause}
                    </p>
                    <p>
                      <span className="text-white/45">Action:</span> {option.action}
                    </p>
                    <p>
                      <span className="text-white/45">Resolution:</span> {option.resolution}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-white/15 bg-black/60 p-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-coral">
          4. AI recommendation
        </p>
        <p className="mt-2 text-sm text-white/85">{plan.recommended_solution}</p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-black/50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-white/45">
            5. Required actions for analyst
          </p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-white/75">
            {plan.required_actions.map((step, idx) => (
              <li key={idx}>{step}</li>
            ))}
          </ol>
        </div>
        <div className="rounded-xl border border-white/10 bg-black/50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-white/45">
            6. Required supporting documents
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-white/75">
            {plan.required_documents.map((doc, idx) => (
              <li key={idx}>{doc}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-white/45">
          7. Expected outcome (never auto-applied)
        </p>
        <p className="mt-1.5 text-xs text-white/75">{plan.expected_outcome}</p>
      </div>
    </div>
  );
}
