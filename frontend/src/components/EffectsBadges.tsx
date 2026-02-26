import type { Effects } from "../types";

export function EffectsBadges({ effects }: { effects?: Effects }) {
  if (!effects) {
    return null;
  }

  const items = [
    effects.leader_changed && "Смена лидера",
    effects.has_large_contribution && "Крупный вклад",
    effects.ending_soon && "Скоро завершение",
    effects.has_new_activity && "Новые действия",
  ].filter(Boolean);

  return (
    <div className="badges">
      {items.length ? items.map((item) => <span key={item}>{item}</span>) : <span>Без новых эффектов</span>}
    </div>
  );
}
