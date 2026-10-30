import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, CalendarDays,
  Check, CheckCheck, ChevronDown, ChevronLeft, ChevronRight, CircleAlert,
  Clock3, Download, FileBarChart2, Filter, LayoutDashboard, ListChecks,
  Menu, MoreHorizontal, Phone, Search, ShieldCheck, SlidersHorizontal,
  Users, WalletCards, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
  Bar, BarChart,
} from "recharts";
import api, { errorMessage, exportCollections } from "./api";

const NAV_ITEMS = [
  { id: "Overview", label: "Overview", icon: LayoutDashboard },
  { id: "Priority queue", label: "Priority queue", icon: ListChecks },
  { id: "Customers", label: "Customers", icon: Users },
  { id: "Follow-ups", label: "Follow-ups", icon: CalendarDays },
  { id: "Analytics", label: "Analytics", icon: FileBarChart2 },
];

const money = (value, compact = false) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 0,
  ...(compact ? { notation: "compact", maximumFractionDigits: 1 } : {}),
}).format(Number(value || 0));

const dateLabel = (value, options = { month: "short", day: "numeric" }) => value
  ? new Intl.DateTimeFormat("en-US", options).format(new Date(value))
  : "—";

const initials = (name = "") => name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();

function Avatar({ name, size = "normal" }) {
  const colors = ["avatar-blue", "avatar-mint", "avatar-violet", "avatar-amber"];
  const color = colors[(name || "").charCodeAt(0) % colors.length];
  return <span className={`avatar ${color} ${size === "small" ? "avatar-small" : ""}`}>{initials(name)}</span>;
}

function StatusBadge({ status }) {
  const normalized = (status || "OPEN").toLowerCase().replaceAll("_", " ");
  const tone = normalized.includes("disput") || normalized.includes("restrict")
    ? "badge-rose"
    : normalized.includes("missed")
      ? "badge-rose"
    : normalized.includes("overdue") || normalized.includes("open")
      ? "badge-amber"
      : normalized.includes("paid") || normalized.includes("completed") || normalized.includes("current")
        ? "badge-green"
        : "badge-slate";
  return <span className={`status-badge ${tone}`}><span className="badge-dot" />{normalized}</span>;
}

function IconButton({ label, children, onClick, className = "" }) {
  return <button aria-label={label} title={label} className={`icon-button ${className}`} onClick={onClick}>{children}</button>;
}

function EmptyState({ title, message }) {
  return <div className="empty-state"><span className="empty-icon"><Search size={20} /></span><strong>{title}</strong><span>{message}</span></div>;
}

function LoadingState({ message = "Loading account data…" }) {
  return <div className="module-loading" role="status"><div><span className="spinner" /><span>{message}</span></div><div className="loading-skeleton" aria-hidden="true"><i /><i /><i /></div></div>;
}

function InlineError({ message, onRetry }) {
  return <div className="inline-error" role="alert">
    <span className="error-mark"><CircleAlert size={18} /></span>
    <div><strong>We couldn’t load this view</strong><span>{message}</span></div>
    <button className="button button-secondary" onClick={onRetry}>Try again</button>
  </div>;
}

function Pagination({ page, total, pageSize, onChange }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const first = total ? (page - 1) * pageSize + 1 : 0;
  const last = Math.min(page * pageSize, total);
  if (total <= pageSize) return null;
  return <div className="pagination">
    <span>Showing <strong>{first}–{last}</strong> of <strong>{total}</strong></span>
    <div>
      <button aria-label="Previous page" disabled={page === 1} onClick={() => onChange(page - 1)}><ChevronLeft size={15} /></button>
      <span>Page <strong>{page}</strong> of {pageCount}</span>
      <button aria-label="Next page" disabled={page === pageCount} onClick={() => onChange(page + 1)}><ChevronRight size={15} /></button>
    </div>
  </div>;
}

function FollowUpCalendar({ tasks, month, selectedDay, onSelectDay, onMonthChange }) {
  const year = month.getFullYear();
  const monthIndex = month.getMonth();
  const firstWeekday = new Date(year, monthIndex, 1).getDay();
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const counts = new Map();
  for (const task of tasks) {
    const date = new Date(task.due_at);
    if (date.getFullYear() === year && date.getMonth() === monthIndex) {
      const day = date.getDate();
      counts.set(day, (counts.get(day) || 0) + 1);
    }
  }
  const selectedKey = selectedDay ? `${selectedDay.getFullYear()}-${selectedDay.getMonth()}-${selectedDay.getDate()}` : "";
  const dateKey = (day) => `${year}-${monthIndex}-${day}`;
  const monthName = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" }).format(month);
  const today = new Date();
  return <div className="followup-calendar">
    <div className="calendar-header">
      <div><span className="eyebrow">YOUR MONTH</span><strong>{monthName}</strong></div>
      <div className="calendar-controls">
        <button aria-label="Previous month" onClick={() => onMonthChange(new Date(year, monthIndex - 1, 1))}><ChevronLeft size={16} /></button>
        <button aria-label="Next month" onClick={() => onMonthChange(new Date(year, monthIndex + 1, 1))}><ChevronRight size={16} /></button>
      </div>
    </div>
    <div className="calendar-grid" role="grid" aria-label={`${monthName} follow-ups`}>
      {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((day) => <span className="calendar-weekday" key={day}>{day}</span>)}
      {Array.from({ length: firstWeekday }, (_, index) => <span className="calendar-blank" key={`blank-${index}`} />)}
      {Array.from({ length: daysInMonth }, (_, index) => {
        const day = index + 1;
        const isToday = today.getFullYear() === year && today.getMonth() === monthIndex && today.getDate() === day;
        return <button
          key={day}
          className={`calendar-day ${counts.has(day) ? "calendar-has-tasks" : ""} ${selectedKey === dateKey(day) ? "calendar-selected" : ""} ${isToday ? "calendar-today" : ""}`}
          aria-label={`${monthName.split(" ")[0]} ${day}${counts.has(day) ? `, ${counts.get(day)} follow-ups` : ""}`}
          aria-pressed={selectedKey === dateKey(day)}
          onClick={() => onSelectDay(new Date(year, monthIndex, day))}
        >{day}{counts.has(day) && <i />}</button>;
      })}
    </div>
    <div className="calendar-legend"><span><i />Scheduled follow-ups</span><button onClick={() => onSelectDay(null)}>Clear day filter</button></div>
  </div>;
}

function MetricCard({ label, value, note, icon: Icon, tint, trend }) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span className={`metric-icon ${tint}`}><Icon size={18} strokeWidth={2} /></span>
        {trend && <span className="metric-trend"><ArrowUpRight size={14} />{trend}</span>}
      </div>
      <p className="metric-label">{label}</p>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </article>
  );
}

function PanelHeading({ title, subtitle, action }) {
  return <div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>;
}

function SearchField({ value, onChange, placeholder = "Search customers, accounts..." }) {
  return <label className="search-field"><Search size={17} /><input data-global-search value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /><kbd>⌘ K</kbd></label>;
}

function Toast({ toast, dismiss }) {
  if (!toast) return null;
  return <div className={`toast ${toast.kind === "error" ? "toast-error" : ""}`} role="status">
    {toast.kind === "error" ? <CircleAlert size={18} /> : <Check size={18} />}
    <span>{toast.message}</span><button aria-label="Dismiss notification" onClick={dismiss}><X size={15} /></button>
  </div>;
}

function DialogFrame({ title, subtitle, onClose, children, wide = false }) {
  return <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className={`dialog ${wide ? "dialog-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
      <div className="dialog-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><IconButton label="Close dialog" onClick={onClose}><X size={18} /></IconButton></div>
      {children}
    </section>
  </div>;
}

function CallDialog({ account, agents, onClose, onSaved, notify }) {
  const [outcome, setOutcome] = useState("NOT_REACHABLE");
  const [notes, setNotes] = useState("");
  const [promiseDate, setPromiseDate] = useState("");
  const [paymentAmount, setPaymentAmount] = useState("");
  const [followUpAt, setFollowUpAt] = useState("");
  const [agentId, setAgentId] = useState(agents[0]?.id || "");
  const [reviewApproved, setReviewApproved] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const restricted = account.requires_review;

  async function saveCall() {
    setSaving(true);
    try {
      await api.post("/calls", {
        loan_id: account.id,
        agent_id: Number(agentId),
        outcome,
        notes: notes.trim(),
        ...(outcome === "PROMISED_TO_PAY" ? { promise_date: promiseDate } : {}),
        ...(outcome === "PAID" ? { payment_amount: Number(paymentAmount) } : {}),
        ...(outcome === "NOT_REACHABLE" && followUpAt ? { follow_up_at: new Date(followUpAt).toISOString() } : {}),
        human_review_approved: reviewApproved,
      });
      notify("Call outcome recorded successfully.");
      onSaved();
    } catch (error) {
      notify(errorMessage(error), "error");
      setConfirm(false);
    } finally {
      setSaving(false);
    }
  }

  return <DialogFrame title="Log a collection call" subtitle={`${account.customer_name} · ${account.loan_id}`} onClose={onClose}>
    {confirm ? <div className="confirm-content">
      <span className="confirm-mark"><Phone size={20} /></span>
      <h3>Save this call outcome?</h3>
      <p>This will add a permanent call record to {account.customer_name}’s account{outcome === "PAID" ? " and update the balance" : ""}.</p>
      <div className="dialog-actions"><button className="button button-quiet" onClick={() => setConfirm(false)} disabled={saving}>Go back</button><button className="button button-primary" onClick={saveCall} disabled={saving}>{saving ? "Saving…" : "Confirm outcome"}</button></div>
    </div> : <form className="dialog-form" onSubmit={(event) => { event.preventDefault(); setConfirm(true); }}>
      <div className="account-context">
        <div><span className="context-label">Outstanding balance</span><strong>{money(account.outstanding_amount)}</strong></div>
        <div><span className="context-label">Days past due</span><strong>{account.days_past_due} days</strong></div>
      </div>
      {restricted && <div className="review-notice"><ShieldCheck size={18} /><div><strong>Human review required</strong><span>{account.review_reasons.join(" · ")}. Confirm review before any outreach is recorded.</span></div></div>}
      <label className="form-label">Call outcome</label>
      <div className="outcome-grid">
        {[
          ["NOT_REACHABLE", "No answer"],
          ["PROMISED_TO_PAY", "Promised to pay"],
          ["PAID", "Payment made"],
          ["DISPUTE", "Dispute raised"],
        ].map(([value, label]) => <button key={value} type="button" className={`outcome-option ${outcome === value ? "outcome-selected" : ""}`} onClick={() => setOutcome(value)}>{label}</button>)}
      </div>
      {outcome === "PROMISED_TO_PAY" && <label className="form-label">Promised payment date<input required type="date" min={new Date().toISOString().slice(0, 10)} value={promiseDate} onChange={(event) => setPromiseDate(event.target.value)} /></label>}
      {outcome === "PAID" && <label className="form-label">Payment amount (up to {money(account.outstanding_amount)})<div className="input-prefix"><span>$</span><input required min="0.01" max={account.outstanding_amount} step="0.01" type="number" value={paymentAmount} onChange={(event) => setPaymentAmount(event.target.value)} placeholder="0.00" /></div></label>}
      <label className="form-label">Call notes<textarea required minLength={2} maxLength={4000} rows="3" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Summarize the conversation and agreed next steps…" /></label>
      {outcome === "NOT_REACHABLE" && <label className="form-label">Optional follow-up date<input type="datetime-local" value={followUpAt} onChange={(event) => setFollowUpAt(event.target.value)} /></label>}
      <label className="form-label">Assigned agent<select value={agentId} onChange={(event) => setAgentId(event.target.value)}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
      {restricted && <label className="review-checkbox"><input type="checkbox" checked={reviewApproved} onChange={(event) => setReviewApproved(event.target.checked)} /><span>I reviewed this account and confirm outreach is permitted under applicable policy.</span></label>}
      <div className="dialog-actions"><button type="button" className="button button-quiet" onClick={onClose}>Cancel</button><button className="button button-primary" disabled={!notes.trim() || !agentId || (restricted && !reviewApproved) || (outcome === "PROMISED_TO_PAY" && !promiseDate) || (outcome === "PAID" && (!paymentAmount || Number(paymentAmount) > account.outstanding_amount))}>Review &amp; save call <ArrowRight size={16} /></button></div>
    </form>}
  </DialogFrame>;
}

function FollowUpDialog({ accounts, agents, onClose, onSaved, notify }) {
  const [loanId, setLoanId] = useState("");
  const [agentId, setAgentId] = useState(agents[0]?.id || "");
  const [dueAt, setDueAt] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const eligible = accounts.filter((account) => account.outstanding_amount > 0);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    try {
      await api.post("/followups", {
        loan_id: Number(loanId), agent_id: Number(agentId),
        due_at: new Date(dueAt).toISOString(), kind: "CALL", notes,
      });
      notify("Follow-up scheduled.");
      onSaved();
    } catch (error) {
      notify(errorMessage(error), "error");
    } finally {
      setSaving(false);
    }
  }

  return <DialogFrame title="Schedule a follow-up" subtitle="Create a task for your collections queue." onClose={onClose}>
    <form className="dialog-form" onSubmit={submit}>
      <label className="form-label">Customer account<select required value={loanId} onChange={(event) => setLoanId(event.target.value)}><option value="">Select an account…</option>{eligible.map((account) => <option key={account.id} value={account.id}>{account.customer_name} · {account.loan_id}</option>)}</select></label>
      <label className="form-label">Due date and time<input required type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} min={new Date().toISOString().slice(0, 16)} /></label>
      <label className="form-label">Assign to<select required value={agentId} onChange={(event) => setAgentId(event.target.value)}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
      <label className="form-label">Task notes<textarea rows="3" maxLength="2000" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Add context for the next touchpoint…" /></label>
      <div className="dialog-actions"><button type="button" className="button button-quiet" onClick={onClose}>Cancel</button><button className="button button-primary" disabled={!loanId || !dueAt || !agentId || saving}>{saving ? "Scheduling…" : "Create follow-up"}</button></div>
    </form>
  </DialogFrame>;
}

function CustomerProfile({ customerId, onClose, onCall }) {
  const [customer, setCustomer] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api.get(`/customers/${customerId}`).then(({ data }) => { if (active) setCustomer(data); })
      .catch((failure) => { if (active) setError(errorMessage(failure)); });
    return () => { active = false; };
  }, [customerId]);

  const activity = useMemo(() => {
    if (!customer) return [];
    return customer.loans.flatMap((loan) => [
      ...loan.calls.map((call) => ({ ...call, type: "call", date: call.contacted_at, loan })),
      ...loan.payments.map((payment) => ({ ...payment, type: "payment", date: payment.paid_at, loan })),
      ...loan.followups.map((followup) => ({ ...followup, type: "followup", date: followup.due_at, loan })),
      ...loan.promises.map((promise) => ({ ...promise, type: "promise", date: promise.due_at, loan })),
    ]).sort((a, b) => new Date(b.date) - new Date(a.date));
  }, [customer]);

  return <div className="overlay overlay-right" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="profile-drawer" role="dialog" aria-modal="true" aria-label="Customer profile">
      <div className="drawer-top"><span className="eyebrow">CUSTOMER PROFILE</span><IconButton label="Close profile" onClick={onClose}><X size={18} /></IconButton></div>
      {!customer && !error && <div className="profile-loading"><span className="spinner" />Loading customer profile…</div>}
      {error && <EmptyState title="Couldn’t load profile" message={error} />}
      {customer && <>
        <div className="profile-person"><Avatar name={customer.full_name} /><div><h2>{customer.full_name}</h2><p>{customer.city}, {customer.state}</p></div></div>
        <div className="profile-contact"><span>{customer.email}</span><span>{customer.phone}</span><span>Prefers {customer.preferred_contact.toLowerCase()}</span></div>
        {customer.contact_restricted && <div className="review-notice"><ShieldCheck size={18} /><div><strong>Contact restricted</strong><span>Human review is required before outreach.</span></div></div>}
        <div className="drawer-section"><PanelHeading title="Loan accounts" subtitle={`${customer.loans.length} account${customer.loans.length === 1 ? "" : "s"}`} />
          {customer.loans.map((loan) => <div className="loan-card" key={loan.id}>
            <div className="loan-card-top"><div><span className="loan-number">{loan.loan_id}</span><span className="loan-product">{loan.product}</span></div><StatusBadge status={loan.status} /></div>
            <div className="loan-balance"><div><span>Outstanding</span><strong>{money(loan.outstanding_amount)}</strong></div><div><span>Days past due</span><strong>{loan.days_past_due}</strong></div></div>
            <div className="loan-agent">Managed by {loan.agent_name}</div>
            {loan.outstanding_amount > 0 && <button className="button button-secondary button-full" onClick={() => onCall({
              id: loan.id, loan_id: loan.loan_id, customer_name: customer.full_name,
              outstanding_amount: loan.outstanding_amount, days_past_due: loan.days_past_due,
              requires_review: customer.contact_restricted || loan.is_disputed,
              review_reasons: [loan.is_disputed && "Account is in dispute", customer.contact_restricted && "Customer has a contact restriction"].filter(Boolean),
            })}><Phone size={15} /> Log a call</button>}
          </div>)}
        </div>
        <div className="drawer-section"><PanelHeading title="Account activity" subtitle="Payments, calls and follow-ups" />
          {activity.length === 0 ? <EmptyState title="No activity yet" message="Account activity will appear here." /> : <div className="timeline">
            {activity.map((item) => <div className="timeline-item" key={`${item.type}-${item.id}`}>
              <span className={`timeline-icon timeline-${item.type}`}>{item.type === "payment" ? <WalletCards size={14} /> : item.type === "call" ? <Phone size={14} /> : item.type === "promise" ? <CheckCheck size={14} /> : <CalendarDays size={14} />}</span>
              <div><strong>{item.type === "payment" ? `${money(item.amount)} payment` : item.type === "call" ? item.outcome.replaceAll("_", " ").toLowerCase() : item.type === "promise" ? `Payment promise ${item.status.toLowerCase()}` : `Follow-up ${item.status.toLowerCase()}`}</strong><p>{item.type === "call" ? item.notes : item.type === "followup" ? item.notes || item.kind.replaceAll("_", " ").toLowerCase() : item.type === "promise" ? `Commitment due · ${item.loan.loan_id}` : `${item.method} · ${item.loan.loan_id}`}</p><time>{dateLabel(item.date, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })}</time></div>
            </div>)}
          </div>}
        </div>
      </>}
    </section>
  </div>;
}

function QueueTable({ accounts, onCall, onProfile }) {
  if (!accounts.length) return <EmptyState title="No accounts match your filters" message="Try a different search or status." />;
  return <div className="table-scroll"><table className="data-table queue-table"><thead><tr>
    <th>Customer</th><th>Loan ID</th><th>Outstanding</th><th>Days past due</th><th>Priority score</th><th>Status</th><th>Last contact</th><th />
  </tr></thead><tbody>
    {accounts.map((account) => <tr key={account.id}>
      <td><button className="customer-cell" onClick={() => onProfile(account.customer_id)}><Avatar name={account.customer_name} size="small" /><span><strong>{account.customer_name}</strong><small>{account.city}</small></span></button></td>
      <td><span className="table-id">{account.loan_id}</span></td>
      <td className="amount-cell">{money(account.outstanding_amount)}</td>
      <td>{account.days_past_due > 0 ? <span className="dpd-value">{account.days_past_due} days</span> : <span className="muted-cell">On track</span>}</td>
      <td><div className="priority-value"><span className={`priority-score ${account.priority_score >= 65 ? "priority-high" : account.priority_score >= 38 ? "priority-medium" : "priority-low"}`}>{account.priority_score.toFixed(1)}</span><span className="priority-meter"><i style={{ width: `${Math.min(account.priority_score, 100)}%` }} /></span><span className="priority-tip" title={account.priority_explanation}>ⓘ</span></div></td>
      <td><div className="status-stack"><StatusBadge status={account.status} />{account.requires_review && <span className="review-chip" title={account.review_reasons.join(" · ")}><ShieldCheck size={12} />Review only</span>}</div></td>
      <td className="muted-cell">{dateLabel(account.last_contact)}</td>
      <td><div className="row-actions">{account.outstanding_amount > 0 && <IconButton label={`Log call for ${account.customer_name}`} className="call-icon-button" onClick={() => onCall(account)}><Phone size={15} /></IconButton>}<IconButton label="View profile" onClick={() => onProfile(account.customer_id)}><MoreHorizontal size={17} /></IconButton></div></td>
    </tr>)}
  </tbody></table></div>;
}

function App() {
  const [page, setPage] = useState("Overview");
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [dashboard, setDashboard] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [accountRefresh, setAccountRefresh] = useState(0);
  const [customers, setCustomers] = useState([]);
  const [agents, setAgents] = useState([]);
  const [followups, setFollowups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [accountsLoading, setAccountsLoading] = useState(false);
  const [customersLoading, setCustomersLoading] = useState(false);
  const [followupsLoading, setFollowupsLoading] = useState(false);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState("");
  const [accountsError, setAccountsError] = useState("");
  const [customersError, setCustomersError] = useState("");
  const [followupsError, setFollowupsError] = useState("");
  const [analyticsError, setAnalyticsError] = useState("");
  const [search, setSearch] = useState("");
  const [queueStatus, setQueueStatus] = useState("ALL");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [queuePage, setQueuePage] = useState(1);
  const [customerSearch, setCustomerSearch] = useState("");
  const [customerPage, setCustomerPage] = useState(1);
  const [customerRefresh, setCustomerRefresh] = useState(0);
  const [followupPeriod, setFollowupPeriod] = useState("today");
  const [followupStatus, setFollowupStatus] = useState("OPEN");
  const [calendarMonth, setCalendarMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [selectedFollowupDay, setSelectedFollowupDay] = useState(null);
  const [analyticsRange, setAnalyticsRange] = useState(6);
  const [analyticsRefresh, setAnalyticsRefresh] = useState(0);
  const [profileId, setProfileId] = useState(null);
  const [callAccount, setCallAccount] = useState(null);
  const [followupDialog, setFollowupDialog] = useState(false);
  const [toast, setToast] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [profileMenu, setProfileMenu] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const notify = useCallback((message, kind = "success") => {
    setToast({ message, kind });
    window.setTimeout(() => setToast(null), 4200);
  }, []);

  const refreshCore = useCallback(async () => {
    setRefreshing(true);
    try {
      const [dashboardResponse, accountsResponse, customersResponse, agentsResponse] = await Promise.all([
        api.get("/dashboard"), api.get("/accounts"), api.get("/customers"), api.get("/agents"),
      ]);
      setDashboard(dashboardResponse.data);
      setDashboardError("");
      setAccounts(accountsResponse.data);
      setCustomers(customersResponse.data);
      setAgents(agentsResponse.data);
    } catch (error) {
      setDashboardError(errorMessage(error));
      notify(errorMessage(error), "error");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [notify]);

  useEffect(() => { refreshCore(); }, [refreshCore]);

  useEffect(() => {
    if (page !== "Priority queue") return undefined;
    let active = true;
    const timer = window.setTimeout(async () => {
      setAccountsLoading(true);
      setAccountsError("");
      try {
        const { data } = await api.get("/accounts", {
          params: { search, status: queueStatus, review: reviewOnly ? true : undefined },
        });
        if (active) setAccounts(data);
      } catch (error) { if (active) { setAccountsError(errorMessage(error)); notify(errorMessage(error), "error"); } }
      finally { if (active) setAccountsLoading(false); }
    }, 220);
    return () => { active = false; window.clearTimeout(timer); };
  }, [page, search, queueStatus, reviewOnly, accountRefresh, notify]);

  useEffect(() => {
    if (page !== "Customers") return undefined;
    let active = true;
    const timer = window.setTimeout(async () => {
      setCustomersLoading(true);
      setCustomersError("");
      try {
        const { data } = await api.get("/customers", { params: { search: customerSearch } });
        if (active) setCustomers(data);
      } catch (error) { if (active) { setCustomersError(errorMessage(error)); notify(errorMessage(error), "error"); } }
      finally { if (active) setCustomersLoading(false); }
    }, 220);
    return () => { active = false; window.clearTimeout(timer); };
  }, [page, customerSearch, customerRefresh, notify]);

  const loadFollowups = useCallback(async (signal) => {
    setFollowupsLoading(true);
    setFollowupsError("");
    try {
      const { data } = await api.get("/followups", { params: { period: "all", status: "ALL" }, signal });
      setFollowups(data);
    } catch (error) {
      if (error.code !== "ERR_CANCELED") {
        setFollowupsError(errorMessage(error));
        notify(errorMessage(error), "error");
      }
    } finally {
      if (!signal?.aborted) setFollowupsLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    if (page !== "Follow-ups") return undefined;
    const controller = new AbortController();
    loadFollowups(controller.signal);
    return () => controller.abort();
  }, [page, loadFollowups]);

  useEffect(() => {
    if (page !== "Analytics") return undefined;
    let active = true;
    setAnalyticsLoading(true);
    setAnalyticsError("");
    api.get("/analytics").then(({ data }) => { if (active) setAnalytics(data); })
      .catch((error) => { if (active) { setAnalyticsError(errorMessage(error)); notify(errorMessage(error), "error"); } })
      .finally(() => { if (active) setAnalyticsLoading(false); });
    return () => { active = false; };
  }, [page, analyticsRefresh, notify]);

  useEffect(() => { setQueuePage(1); }, [search, queueStatus, reviewOnly, accountRefresh]);
  useEffect(() => { setCustomerPage(1); }, [customerSearch]);
  useEffect(() => {
    const handleSearchShortcut = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.querySelector("[data-global-search]")?.focus();
      }
    };
    window.addEventListener("keydown", handleSearchShortcut);
    return () => window.removeEventListener("keydown", handleSearchShortcut);
  }, []);

  const metrics = dashboard?.metrics;
  const overdueShare = metrics?.assigned_accounts
    ? Math.round((metrics.overdue_accounts / metrics.assigned_accounts) * 100)
    : 0;

  async function exportReport() {
    setExporting(true);
    try { await exportCollections(); notify("Collections report downloaded."); }
    catch (error) { notify(errorMessage(error), "error"); }
    finally { setExporting(false); }
  }

  async function completeFollowup(item) {
    try {
      await api.patch(`/followups/${item.id}`, { status: "COMPLETED" });
      notify("Follow-up marked complete.");
      await loadFollowups();
      refreshCore();
    } catch (error) { notify(errorMessage(error), "error"); }
  }

  function navigate(nextPage) {
    setPage(nextPage);
    setMobileNav(false);
  }

  const pageSize = 10;
  const visibleAccounts = accounts.slice((queuePage - 1) * pageSize, queuePage * pageSize);
  const visibleCustomers = customers.slice((customerPage - 1) * pageSize, customerPage * pageSize);
  const visibleFollowups = useMemo(() => {
    const startToday = new Date();
    startToday.setHours(0, 0, 0, 0);
    const tomorrow = new Date(startToday);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const isSameDay = (first, second) => first.getFullYear() === second.getFullYear()
      && first.getMonth() === second.getMonth() && first.getDate() === second.getDate();
    return followups.filter((item) => {
      if (followupStatus !== "ALL" && item.status !== followupStatus) return false;
      const due = new Date(item.due_at);
      if (selectedFollowupDay && !isSameDay(due, selectedFollowupDay)) return false;
      if (selectedFollowupDay) return true;
      if (followupPeriod === "today") return isSameDay(due, startToday);
      if (followupPeriod === "upcoming") return due >= tomorrow;
      if (followupPeriod === "overdue") return due < startToday && ["OPEN", "MISSED"].includes(item.status);
      return true;
    }).sort((first, second) => new Date(first.due_at) - new Date(second.due_at));
  }, [followups, followupPeriod, followupStatus, selectedFollowupDay]);
  const visibleTrend = (analytics?.recovery_trend || []).slice(-analyticsRange);

  if (loading) return <div className="app-loading"><div className="loading-brand"><span className="brand-mark">C</span><strong>Collect<span>Flow</span></strong></div><span className="spinner" /><p>Getting your workbench ready…</p></div>;

  return <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
    {mobileNav && <button className="mobile-backdrop" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? "sidebar-mobile-open" : ""}`}>
      <div className="brand-lockup"><span className="brand-mark">C</span>{!collapsed && <span className="brand-name">Collect<span>Flow</span></span>}<button className="mobile-nav-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={18} /></button></div>
      {!collapsed && <div className="workspace-label">WORKSPACE</div>}
      <nav className="side-nav">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => <button key={id} title={collapsed ? label : undefined} onClick={() => navigate(id)} className={`nav-item ${page === id ? "nav-active" : ""}`}><Icon size={18} /><span>{label}</span>{id === "Follow-ups" && metrics?.todays_followups > 0 && !collapsed && <small>{metrics.todays_followups}</small>}</button>)}
      </nav>
      {!collapsed && <div className="sidebar-bottom">
        <div className="sidebar-tip"><span className="tip-icon"><Activity size={17} /></span><strong>Daily momentum</strong><p>Stay consistent. Every conversation moves an account forward.</p><div className="tip-progress"><i style={{ width: `${Math.min(100, metrics?.assigned_accounts ? (metrics.overdue_accounts / metrics.assigned_accounts) * 100 : 0)}%` }} /></div><small>{metrics?.overdue_accounts || 0} accounts need attention</small></div>
        <button className="help-link" onClick={() => setHelpOpen(true)}>Workspace guide <ArrowRight size={14} /></button>
      </div>}
      <button className="collapse-toggle" onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}><ChevronLeft size={17} /><span>Collapse menu</span></button>
    </aside>

    <main className="main-area">
      <header className="topbar">
        <div className="topbar-left"><button className="mobile-menu-button" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20} /></button><div className="breadcrumbs"><span>Workspace</span><ChevronRight size={14} /><strong>{page}</strong></div></div>
        <div className="topbar-right">
          <div className="date-stamp"><CalendarDays size={15} /><span>{dateLabel(new Date(), { weekday: "short", month: "short", day: "numeric" })}</span></div>
          <button className="notification-button" title="Notifications" onClick={() => navigate("Follow-ups")}><Bell size={18} />{metrics?.todays_followups > 0 && <i />}</button>
          <div className="profile-menu-wrap"><button className="profile-menu-button" onClick={() => setProfileMenu(!profileMenu)}><Avatar name={agents[0]?.name || "Alex Morgan"} size="small" /><span className="profile-name">{agents[0]?.name || "Alex Morgan"}<small>Collections agent</small></span><ChevronDown size={15} /></button>
            {profileMenu && <div className="profile-dropdown"><strong>{agents[0]?.name || "Alex Morgan"}</strong><span>{agents[0]?.email || "alex.morgan@collectflow.demo"}</span><span className="profile-role">Collections agent · Demo workspace</span></div>}
          </div>
        </div>
      </header>

      <div className="page-content">
        {dashboardError && !dashboard && <InlineError message={dashboardError} onRetry={refreshCore} />}
        {page === "Overview" && <section>
          <div className="page-heading-row"><div><span className="eyebrow">YOUR COLLECTIONS, AT A GLANCE</span><h1>Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 17 ? "afternoon" : "evening"}, {agents[0]?.name?.split(" ")[0] || "Alex"} <span className="wave">✦</span></h1><p>Here’s what’s happening across your accounts today.</p></div><button className="button button-secondary" disabled={refreshing} onClick={refreshCore}><Activity size={15} className={refreshing ? "spin-icon" : ""} />{refreshing ? "Refreshing…" : "Refresh data"}</button></div>
          <div className="metric-grid">
            <MetricCard label="Assigned accounts" value={metrics?.assigned_accounts ?? "—"} note="Across your active portfolio" icon={Users} tint="tint-blue" />
            <MetricCard label="Total outstanding" value={money(metrics?.total_outstanding, true)} note="Remaining across all accounts" icon={WalletCards} tint="tint-violet" />
            <MetricCard label="Recovered this month" value={money(metrics?.recovered_this_month, true)} note={`${money(metrics?.recovered_total)} collected all-time`} icon={ArrowUpRight} tint="tint-mint" trend={metrics?.recovered_this_month > 0 ? "This month" : undefined} />
            <MetricCard label="Recovery rate" value={`${metrics?.recovery_rate ?? 0}%`} note="Recovered vs. total loan principal" icon={Activity} tint="tint-amber" />
          </div>
          <div className="dashboard-grid">
            <article className="panel recovery-panel">
              <PanelHeading title="Recovery trend" subtitle="Collected payments · last 6 months" action={<span className="chart-period"><span className="chart-legend-dot" />Recovered</span>} />
              <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={dashboard?.recovery_trend || []} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}>
                <defs><linearGradient id="recoveryGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3568e8" stopOpacity={0.19} /><stop offset="95%" stopColor="#3568e8" stopOpacity={0.015} /></linearGradient></defs>
                <CartesianGrid stroke="#eef1f6" vertical={false} />
                <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 12 }} dy={12} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 11 }} tickFormatter={(value) => money(value, true)} width={58} />
                <Tooltip formatter={(value) => [money(value), "Recovered"]} contentStyle={{ borderRadius: 12, border: "1px solid #e8ecf3", boxShadow: "0 8px 24px #172b4d12" }} />
                <Area type="monotone" dataKey="recovered" stroke="#3568e8" strokeWidth={2.5} fill="url(#recoveryGradient)" activeDot={{ r: 5, strokeWidth: 0, fill: "#3568e8" }} />
              </AreaChart></ResponsiveContainer></div>
              <div className="chart-caption"><span><span className="caption-dot" />Monthly recovery</span><strong>{money(metrics?.recovered_this_month)} <small>this month</small></strong></div>
            </article>
            <article className="panel performance-panel">
              <PanelHeading title="Agent performance" subtitle="All-time recovered amount" />
              <div className="agent-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={dashboard?.agent_performance || []} margin={{ top: 12, right: 4, left: -20, bottom: 2 }}>
                <CartesianGrid stroke="#eef1f6" horizontal vertical={false} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 11 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 10 }} tickFormatter={(value) => money(value, true)} />
                <Tooltip formatter={(value) => [money(value), "Recovered"]} contentStyle={{ borderRadius: 12, border: "1px solid #e8ecf3", boxShadow: "0 8px 24px #172b4d12" }} />
                <Bar dataKey="recovered" fill="#6d8ff0" radius={[5, 5, 0, 0]} maxBarSize={27} />
              </BarChart></ResponsiveContainer></div>
              <div className="performance-footer"><span className="performance-avatar-stack">{agents.slice(0, 4).map((agent) => <Avatar key={agent.id} name={agent.name} size="small" />)}</span><span>{agents.length} active agents</span><button onClick={() => navigate("Analytics")}>View analytics <ArrowRight size={14} /></button></div>
            </article>
          </div>
          <div className="bottom-grid">
            <article className="panel activity-panel">
              <PanelHeading title="Recent activity" subtitle="Latest account updates" action={<button className="text-button" onClick={() => navigate("Customers")}>View customers <ArrowRight size={14} /></button>} />
              {!dashboard?.recent_activities?.length ? <EmptyState title="No recent activity" message="Calls and payments will appear here." /> : <div className="activity-list">
                {dashboard.recent_activities.slice(0, 6).map((item) => <div className="activity-row" key={item.id}>
                  <span className={`activity-type-icon ${item.type === "payment" ? "activity-payment" : "activity-call"}`}>{item.type === "payment" ? <WalletCards size={15} /> : <Phone size={15} />}</span>
                  <div className="activity-copy"><strong>{item.customer_name}</strong><span>{item.description} · {item.agent_name}</span></div>
                  <div className="activity-meta">{item.amount != null && <strong>{money(item.amount)}</strong>}<time>{dateLabel(item.created_at)}</time></div>
                </div>)}
              </div>}
            </article>
            <article className="panel focus-panel">
              <PanelHeading title="Today’s focus" subtitle="A few numbers to guide your day" />
              <button className="focus-metric" onClick={() => { setFollowupPeriod("today"); navigate("Follow-ups"); }}><span className="focus-icon tint-blue"><CalendarDays size={17} /></span><span><strong>{metrics?.todays_followups ?? 0}</strong><small>Follow-ups due today</small></span><ChevronRight size={16} /></button>
              <button className="focus-metric" onClick={() => { setQueueStatus("OVERDUE"); setReviewOnly(false); navigate("Priority queue"); }}><span className="focus-icon tint-amber"><Clock3 size={17} /></span><span><strong>{metrics?.overdue_accounts ?? 0}</strong><small>Overdue accounts</small></span><ChevronRight size={16} /></button>
              <button className="focus-metric" onClick={() => { setQueueStatus("ALL"); setReviewOnly(true); navigate("Priority queue"); }}><span className="focus-icon tint-rose"><ShieldCheck size={17} /></span><span><strong>{metrics?.accounts_needing_review ?? 0}</strong><small>Need human review</small></span><ChevronRight size={16} /></button>
              <div className="focus-progress"><div><span>Overdue portfolio</span><strong>{overdueShare}%</strong></div><div className="progress-track"><i style={{ width: `${overdueShare}%` }} /></div><small>of assigned accounts need follow-up</small></div>
            </article>
          </div>
        </section>}

        {page === "Priority queue" && <section>
          <div className="page-heading-row"><div><span className="eyebrow">SMARTER OUTREACH, BETTER OUTCOMES</span><h1>Priority queue</h1><p>Work the right accounts first, with clear reasons behind every score.</p></div><button className="button button-primary" onClick={() => { const next = accounts.find((item) => item.outstanding_amount > 0 && !item.requires_review); if (next) setCallAccount(next); else notify("No eligible accounts are ready for outreach.", "info"); }}><Phone size={16} />Start next call</button></div>
          <article className="panel queue-panel">
            <div className="queue-toolbar"><SearchField value={search} onChange={setSearch} /><label className="select-control"><Filter size={15} /><select value={queueStatus} onChange={(event) => setQueueStatus(event.target.value)}><option value="ALL">All statuses</option><option value="OVERDUE">Overdue</option><option value="CURRENT">Current</option><option value="PAID">Paid</option><option value="DISPUTED">Disputed</option></select></label><button className={`filter-toggle ${reviewOnly ? "filter-toggle-active" : ""}`} onClick={() => setReviewOnly(!reviewOnly)}><SlidersHorizontal size={15} />{reviewOnly ? "Review required" : "All accounts"}</button><span className="result-count">{accounts.length} accounts</span></div>
            <div className="priority-explainer"><span className="explainer-mark">i</span><span><strong>Priority score</strong> is a transparent weighted ranking: outstanding balance (40%), days overdue (35%), and historical contact outcomes (25%). Disputed, restricted, and paid accounts are excluded from routine outreach and shown for review. Hover over the ⓘ beside a score to see its breakdown.</span></div>
            {accountsError ? <InlineError message={accountsError} onRetry={() => setAccountRefresh((value) => value + 1)} /> : accountsLoading ? <LoadingState message="Refreshing priority scores…" /> : <>
              <QueueTable accounts={visibleAccounts} onCall={setCallAccount} onProfile={setProfileId} />
              <Pagination page={queuePage} total={accounts.length} pageSize={pageSize} onChange={setQueuePage} />
            </>}
          </article>
        </section>}

        {page === "Customers" && <section>
          <div className="page-heading-row"><div><span className="eyebrow">YOUR CUSTOMER PORTFOLIO</span><h1>Customers</h1><p>Borrower details, loan balances and a complete activity history.</p></div><span className="page-count">{visibleCustomers.length} customers</span></div>
          <article className="panel customer-list-panel"><div className="queue-toolbar"><SearchField value={customerSearch} onChange={setCustomerSearch} placeholder="Search by name, email or phone..." /><span className="result-count">{visibleCustomers.length} results</span></div>
            {customersError ? <InlineError message={customersError} onRetry={() => setCustomerRefresh((value) => value + 1)} /> : customersLoading ? <LoadingState message="Searching customers…" /> : !customers.length ? <EmptyState title="No customers found" message="Try another name, email or phone number." /> : <><div className="table-scroll"><table className="data-table"><thead><tr><th>Customer</th><th>Contact</th><th>Location</th><th>Accounts</th><th>Total outstanding</th><th>Contact preference</th><th /></tr></thead><tbody>
              {visibleCustomers.map((customer) => <tr key={customer.id}>
                <td><button className="customer-cell" onClick={() => setProfileId(customer.id)}><Avatar name={customer.full_name} size="small" /><span><strong>{customer.full_name}</strong><small>{customer.contact_restricted ? "Human review required" : customer.email}</small></span></button></td>
                <td><span className="contact-text">{customer.phone}</span><small className="table-subtext">{customer.email}</small></td>
                <td>{customer.city}, {customer.state}</td><td>{customer.loan_count}</td><td className="amount-cell">{money(customer.total_outstanding)}</td><td><span className="preference-pill">{customer.preferred_contact}</span></td><td><IconButton label={`Open ${customer.full_name} profile`} onClick={() => setProfileId(customer.id)}><ChevronRight size={17} /></IconButton></td>
              </tr>)}
            </tbody></table></div><Pagination page={customerPage} total={customers.length} pageSize={pageSize} onChange={setCustomerPage} /></>}
          </article>
        </section>}

        {page === "Follow-ups" && <section>
          <div className="page-heading-row"><div><span className="eyebrow">NEVER MISS A COMMITMENT</span><h1>Follow-ups</h1><p>Keep payment promises and account touchpoints on schedule.</p></div><button className="button button-primary" onClick={() => setFollowupDialog(true)}><CalendarDays size={16} />Schedule follow-up</button></div>
          <div className="followup-summary">
            <button className={`followup-summary-card ${followupPeriod === "today" && !selectedFollowupDay ? "summary-active" : ""}`} onClick={() => { setSelectedFollowupDay(null); setFollowupPeriod("today"); }}><span className="summary-icon tint-blue"><CalendarDays size={17} /></span><span><strong>{metrics?.todays_followups ?? 0}</strong><small>Due today</small></span></button>
            <button className={`followup-summary-card ${followupPeriod === "upcoming" && !selectedFollowupDay ? "summary-active" : ""}`} onClick={() => { setSelectedFollowupDay(null); setFollowupPeriod("upcoming"); }}><span className="summary-icon tint-violet"><ArrowUpRight size={17} /></span><span><strong>{metrics?.upcoming_followups ?? 0}</strong><small>Upcoming commitments</small></span></button>
            <button className={`followup-summary-card ${followupPeriod === "overdue" && !selectedFollowupDay ? "summary-active" : ""}`} onClick={() => { setSelectedFollowupDay(null); setFollowupPeriod("overdue"); }}><span className="summary-icon tint-rose"><Clock3 size={17} /></span><span><strong>{metrics?.overdue_followups ?? 0}</strong><small>Overdue follow-ups</small></span></button>
          </div>
          <div className="followup-layout">
            <FollowUpCalendar tasks={followups} month={calendarMonth} selectedDay={selectedFollowupDay} onSelectDay={setSelectedFollowupDay} onMonthChange={(month) => { setCalendarMonth(month); setSelectedFollowupDay(null); }} />
            <article className="panel followup-panel"><div className="followup-toolbar"><div className="tab-list">{[["today", "Today"], ["upcoming", "Upcoming"], ["overdue", "Overdue"], ["all", "All tasks"]].map(([value, label]) => <button className={!selectedFollowupDay && followupPeriod === value ? "tab-active" : ""} onClick={() => { setSelectedFollowupDay(null); setFollowupPeriod(value); }} key={value}>{label}</button>)}</div><label className="select-control"><Filter size={15} /><select value={followupStatus} onChange={(event) => setFollowupStatus(event.target.value)}><option value="OPEN">Open tasks</option><option value="MISSED">Missed</option><option value="COMPLETED">Completed</option><option value="CANCELLED">Cancelled</option><option value="ALL">All statuses</option></select></label></div>
            {selectedFollowupDay && <div className="selected-day-label">Showing follow-ups for {dateLabel(selectedFollowupDay, { weekday: "long", month: "long", day: "numeric" })}<button onClick={() => setSelectedFollowupDay(null)}>Clear date</button></div>}
            {followupsError ? <InlineError message={followupsError} onRetry={() => loadFollowups()} /> : followupsLoading ? <LoadingState message="Loading follow-ups and checking missed promises…" /> : !visibleFollowups.length ? <EmptyState title="Nothing on your schedule" message="No follow-ups match these filters. Add a task or check another time period." /> : <div className="table-scroll"><table className="data-table"><thead><tr><th>Customer</th><th>Account</th><th>Due</th><th>Task</th><th>Assigned to</th><th>Status</th><th /></tr></thead><tbody>{visibleFollowups.map((item) => <tr key={item.id}>
              <td><button className="customer-cell" onClick={() => setProfileId(item.customer_id)}><Avatar name={item.customer_name} size="small" /><span><strong>{item.customer_name}</strong><small>{money(item.outstanding_amount)} outstanding</small></span></button></td>
              <td><span className="table-id">{item.loan_number}</span></td>
              <td><strong className={new Date(item.due_at) < new Date() && item.status === "OPEN" ? "due-overdue" : ""}>{dateLabel(item.due_at, { month: "short", day: "numeric", year: "numeric" })}</strong><small className="table-subtext">{dateLabel(item.due_at, { hour: "numeric", minute: "2-digit" })}</small></td>
              <td><span className="task-name">{item.kind.replaceAll("_", " ").toLowerCase()}</span><small className="table-subtext">{item.promise_status ? `Payment promise ${item.promise_status.toLowerCase()}` : item.notes || "No notes"}</small></td><td>{item.agent_name}</td><td><StatusBadge status={item.status} /></td>
              <td>{item.status === "OPEN" && <button className="complete-button" onClick={() => completeFollowup(item)}><CheckCheck size={14} />Complete</button>}</td>
            </tr>)}</tbody></table></div>}
            </article>
          </div>
        </section>}

        {page === "Analytics" && <section>
          <div className="page-heading-row"><div><span className="eyebrow">MEASURE WHAT MOVES FORWARD</span><h1>Recovery analytics</h1><p>Portfolio performance from your recorded calls, promises and payments.</p></div><button className="button button-secondary" onClick={exportReport} disabled={exporting}><Download size={16} />{exporting ? "Preparing…" : "Export CSV"}</button></div>
          {analyticsError ? <InlineError message={analyticsError} onRetry={() => setAnalyticsRefresh((value) => value + 1)} /> : analyticsLoading ? <LoadingState message="Calculating recovery and promise conversion…" /> : <>
          <div className="metric-grid analytics-metrics">
            <MetricCard label="Payment success rate" value={`${analytics?.payment_success_rate ?? "—"}${analytics ? "%" : ""}`} note={`${analytics?.total_calls ?? 0} recorded calls`} icon={CheckCheck} tint="tint-mint" />
            <MetricCard label="Promise conversion" value={`${analytics?.promise_to_pay_conversion_rate ?? "—"}${analytics ? "%" : ""}`} note={`${analytics?.total_promises ?? 0} payment promises`} icon={ArrowUpRight} tint="tint-blue" />
            <MetricCard label="Recorded payments" value={analytics?.total_payments ?? "—"} note={`${money(metrics?.recovered_total)} recovered all-time`} icon={WalletCards} tint="tint-violet" />
            <MetricCard label="Outstanding portfolio" value={money(metrics?.total_outstanding, true)} note={`${metrics?.overdue_accounts ?? 0} accounts overdue`} icon={ArrowDownRight} tint="tint-amber" />
          </div>
          <div className="dashboard-grid analytics-charts">
            <article className="panel recovery-panel"><PanelHeading title="Monthly recovery" subtitle={`Payments recorded · most recent ${analyticsRange} month${analyticsRange > 1 ? "s" : ""}`} action={<label className="select-control analytics-range"><CalendarDays size={14} /><select aria-label="Recovery chart date range" value={analyticsRange} onChange={(event) => setAnalyticsRange(Number(event.target.value))}><option value={1}>Last month</option><option value={3}>Last 3 months</option><option value={6}>Last 6 months</option></select></label>} /><div className="chart-wrap">{visibleTrend.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={visibleTrend} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}><defs><linearGradient id="analyticsGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3568e8" stopOpacity={0.19} /><stop offset="95%" stopColor="#3568e8" stopOpacity={0.015} /></linearGradient></defs><CartesianGrid stroke="#eef1f6" vertical={false} /><XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 12 }} dy={12} /><YAxis axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 11 }} tickFormatter={(value) => money(value, true)} width={58} /><Tooltip formatter={(value) => [money(value), "Recovered"]} /><Area type="monotone" dataKey="recovered" stroke="#3568e8" strokeWidth={2.5} fill="url(#analyticsGradient)" /></AreaChart></ResponsiveContainer> : <EmptyState title="No recovery data yet" message="Recorded payments will appear here once available." />}</div></article>
            <article className="panel performance-panel"><PanelHeading title="Agent recovery" subtitle="Payments attributed to each agent" /><div className="agent-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={analytics?.agent_performance || []} margin={{ top: 14, right: 4, left: -20, bottom: 2 }}><CartesianGrid stroke="#eef1f6" horizontal vertical={false} /><XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 11 }} /><YAxis axisLine={false} tickLine={false} tick={{ fill: "#8792a3", fontSize: 10 }} tickFormatter={(value) => money(value, true)} /><Tooltip formatter={(value) => [money(value), "Recovered"]} /><Bar dataKey="recovered" fill="#6d8ff0" radius={[5, 5, 0, 0]} maxBarSize={27} /></BarChart></ResponsiveContainer></div></article>
          </div>
          <article className="panel report-panel"><PanelHeading title="Collections report" subtitle="Export account-level balances, priority scores and review flags." action={<button className="button button-primary button-small" disabled={exporting} onClick={exportReport}><Download size={15} />Download report</button>} /><div className="report-info"><span className="report-file"><FileBarChart2 size={20} /></span><div><strong>Collections portfolio · CSV</strong><span>Includes all {metrics?.assigned_accounts ?? 0} accounts and human-review indicators.</span></div><span className="report-badge">Updated just now</span></div></article>
          </>}
        </section>}
      </div>
      <footer className="app-footer"><span>© {new Date().getFullYear()} CollectFlow</span><span><i /> All systems operational</span></footer>
    </main>
    <Toast toast={toast} dismiss={() => setToast(null)} />
    {helpOpen && <div className="overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setHelpOpen(false); }}><section className="dialog help-dialog" role="dialog" aria-modal="true" aria-labelledby="help-title"><div className="dialog-heading"><div><h2 id="help-title">CollectFlow workspace guide</h2><p>Quick pointers for your daily collections workflow.</p></div><IconButton label="Close guide" onClick={() => setHelpOpen(false)}><X size={17} /></IconButton></div><div className="help-content"><div><strong>Prioritize safely</strong><span>Review the score explanation, and follow human-review flags before contacting an account.</span></div><div><strong>Log every outcome</strong><span>Record notes and promises in the call dialog so your activity history stays current.</span></div><div><strong>Keep commitments visible</strong><span>Use the calendar to select a day, or filter by due date and follow-up status.</span></div><div><strong>Measure recovery</strong><span>Analytics includes payment trends, agent performance and downloadable CSV reporting.</span></div><button className="button button-primary" onClick={() => setHelpOpen(false)}>Got it</button></div></section></div>}
    {profileId != null && <CustomerProfile customerId={profileId} onClose={() => setProfileId(null)} onCall={(account) => { setProfileId(null); setCallAccount(account); }} />}
    {callAccount && <CallDialog account={callAccount} agents={agents} notify={notify} onClose={() => setCallAccount(null)} onSaved={() => { setCallAccount(null); refreshCore(); setAccountRefresh((value) => value + 1); if (page === "Follow-ups") loadFollowups(); if (page === "Analytics") api.get("/analytics").then(({ data }) => setAnalytics(data)); }} />}
    {followupDialog && <FollowUpDialog accounts={accounts} agents={agents} notify={notify} onClose={() => setFollowupDialog(false)} onSaved={() => { setFollowupDialog(false); loadFollowups(); refreshCore(); }} />}
  </div>;
}

export default App;
