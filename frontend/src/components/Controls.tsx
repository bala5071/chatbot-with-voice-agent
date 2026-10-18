import type { Route, TenantEntry } from "../api/types";
import type { BudgetView } from "../state/derive";
import { formatCount, routeFromValue, routeValue } from "../state/derive";

export function TenantPicker(props: {
  entries: TenantEntry[];
  selected: string;
  onSelect: (tenantId: string) => void;
}) {
  return (
    <fieldset className="tenants">
      <legend>Tenant</legend>
      {props.entries.map((entry) => (
        <label key={entry.tenant_id} className="tenant">
          <input
            type="radio"
            name="tenant"
            value={entry.tenant_id}
            checked={entry.tenant_id === props.selected}
            onChange={() => {
              props.onSelect(entry.tenant_id);
            }}
          />
          <span className="tenant-name">{entry.tenant_id}</span>
          {entry.usage ? (
            <span className="tenant-plan">
              {entry.usage.plan} plan · {entry.usage.allowed_models.join(", ")}
            </span>
          ) : (
            <span className="tenant-plan error-text">{entry.error?.message ?? "unavailable"}</span>
          )}
        </label>
      ))}
    </fieldset>
  );
}

export function RoutePicker(props: {
  route: Route;
  models: string[];
  onChange: (route: Route) => void;
}) {
  return (
    <label className="field">
      <span>Model choice</span>
      <select
        value={routeValue(props.route)}
        onChange={(e) => {
          props.onChange(routeFromValue(e.target.value));
        }}
      >
        <optgroup label="By quality, within the plan">
          <option value="quality:cheapest">Cheapest</option>
          <option value="quality:balanced">Balanced</option>
          <option value="quality:best">Best</option>
        </optgroup>
        <optgroup label="A specific model">
          {props.models.map((model) => (
            <option key={model} value={`model:${model}`}>
              {model}
            </option>
          ))}
        </optgroup>
      </select>
    </label>
  );
}

export function DowngradeToggle(props: { checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <label className="check">
      <input
        type="checkbox"
        checked={props.checked}
        onChange={(e) => {
          props.onChange(e.target.checked);
        }}
      />
      <span>Allow a cheaper model when this one is missing its latency target</span>
    </label>
  );
}

export function BudgetBar(props: { view: BudgetView }) {
  const { view } = props;
  return (
    <div className="budget">
      <div className="budget-label">
        <span>Token budget, this period</span>
        <span>
          {formatCount(view.used)} / {formatCount(view.budget)}
        </span>
      </div>
      <progress
        max={view.budget}
        value={view.used}
        aria-label="Token budget used"
        className={view.fraction > 0.9 ? "budget-low" : undefined}
      />
      <div className="muted">{formatCount(view.remaining)} tokens left</div>
    </div>
  );
}
