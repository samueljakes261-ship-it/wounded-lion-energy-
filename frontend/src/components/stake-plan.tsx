// Shared BACK-vs-BACK stake plan panel. Values come from the backend
// StakeCalculator / ArbitrageOpportunity output and are never
// recomputed here. Used by the Turkish BACK vs BACK OpportunityCard
// and by Kenyan bookmaker cards.

export function StakeRow({
  label,
  value,
  emphasize,
}: {
  label: string
  value: number
  emphasize?: boolean
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-400">{label}</span>
      <span
        className={
          emphasize
            ? "font-bold text-emerald-400"
            : "font-medium text-slate-100"
        }
      >
        ${value.toFixed(2)}
      </span>
    </div>
  )
}

export type StakePlanValues = {
  homeStake: number
  drawStake: number
  awayStake: number
  totalStake: number
  guaranteedReturn: number
  guaranteedProfit: number
  roi: number
}

export type StakePlanLabels = {
  title: string
  home: string
  draw: string
  away: string
  totalStake: string
  expectedReturn: string
  guaranteedProfit: string
  roi: string
}

export function StakePlanPanel({
  values,
  labels,
}: {
  values: StakePlanValues
  labels: StakePlanLabels
}) {
  return (
    <div className="bg-slate-800 rounded-lg p-4 space-y-2">
      <div className="text-sm font-semibold text-slate-300 mb-1">{labels.title}</div>

      <StakeRow label={labels.home} value={values.homeStake} />
      {labels.draw ? <StakeRow label={labels.draw} value={values.drawStake} /> : null}
      <StakeRow label={labels.away} value={values.awayStake} />

      <div className="!my-3 border-t border-slate-700" />

      <StakeRow label={labels.totalStake} value={values.totalStake} />
      <StakeRow label={labels.expectedReturn} value={values.guaranteedReturn} />
      <StakeRow label={labels.guaranteedProfit} value={values.guaranteedProfit} emphasize />

      <div className="flex items-center justify-between text-sm pt-1">
        <span className="text-slate-400">{labels.roi}</span>
        <span className="font-bold text-cyan-400">{values.roi.toFixed(2)}%</span>
      </div>
    </div>
  )
}
