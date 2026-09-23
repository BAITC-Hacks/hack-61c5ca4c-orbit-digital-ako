export type Role =
  | "coordinator"
  | "consolidator"
  | "distributor"
  | "transit"
  | "terminal"
  | "truncated"
  | "peripheral";
export type NodeRow = {
  gid: string;
  role: Role;
  role_score: number;
  priority_score: number;
  cluster_id: number;
  depth: number | null;
  is_seed: boolean;
  in_deg: number;
  out_deg: number;
  in_kzt: number;
  out_kzt: number;
  turnover: number;
  pass_through: number | null;
  tainted_in_kzt: number;
  taint_share: number;
  block_impact: number | null;
  betweenness: number;
  seed_sources: number;
  p_onward: number | null;
  evidence: string;
  label?: string;
  counterparties?: Edge[];
};
export type Edge = { src: string; dst: string; amount: number; n_tx: number };
export type GraphData = {
  nodes: NodeRow[];
  edges: Edge[];
  available: number;
  limited: boolean;
  overview?: boolean;
};
export type Capability = { key: string; enabled: boolean; message: string };
export type Summary = {
  nodes: number;
  edges: number;
  transactions: number;
  currency: string;
  total_amount: number;
  tainted_flow_kzt: number | null;
  clusters: number;
  runtime_sec: number;
  roles: Record<Role, number>;
  capabilities: Capability[];
  profile: {
    period_label: string;
    period_start: string | null;
    period_end: string | null;
    has_dates: boolean;
    has_seeds: boolean;
  };
  insight: { n: number; removed_share: number; multiseed_clusters: number };
  resilience: {
    n_blocked: number;
    tainted_flow_left: number;
    random_flow_left: number;
  }[];
};
export type Config = {
  roles: Record<string, number>;
  priority_weights: Record<string, number>;
  threshold_mode: "absolute" | "adaptive";
  fast_lag_days: number;
  currency: string;
};
export type Project = {
  id: string;
  name: string;
  created: string;
  status: string;
  summary?: Summary;
  config: Config;
};
export type Quality = {
  ok: boolean;
  findings: { level: string; code: string; count: number; message: string }[];
  profile?: Summary["profile"] & {
    n_nodes: number;
    n_edges: number;
    n_tx: number;
    total_amount: number;
  };
  capabilities?: Capability[];
  seeds?: { requested: number; in_edges: number };
};
export type Preview = {
  id: string;
  name: string;
  format: string;
  encoding?: string;
  sheets: string[];
  columns: string[];
  rows: Record<string, unknown>[];
  proposal: {
    kind: string;
    fields: Record<
      string,
      { column: string; confidence: number; reason: string }
    >;
  };
};
export type MappingFile = {
  file_id: string;
  kind: string;
  fields: Record<string, string>;
  sheet?: string;
};
export type Check = {
  mode?: string;
  checks?: Check[];
  metric?: string;
  value?: number | boolean | null;
  threshold?: number | boolean;
  op?: string;
  ok: boolean;
};
export type Trace = {
  role: Role;
  trace: {
    rule: string;
    role: Role;
    passed: boolean;
    matched: boolean;
    checks: Check;
  }[];
};
export type Cluster = {
  cluster_id: number;
  n_nodes: number;
  n_seed: number;
  sum_kzt_internal: number;
  top_gids: string;
  hypothesis: string;
  n_coordinator: number;
  n_consolidator: number;
  n_truncated: number;
};
export type Simulation = {
  destinations?: { before: DestinationFlow; after: DestinationFlow };
  ids: string[];
  basis: string;
  before: number;
  after: number;
  remaining_share: number;
  random_share: number;
  components_before: number;
  components_after: number;
  largest_component: number;
  clusters: {
    cluster_id: number;
    remaining_nodes: number;
    fragments: number;
  }[];
  sankey: {
    nodes: { name: string }[];
    links: { source: number; target: number; value: number }[];
  };
};
export type DestinationFlow = {
  nodes: { name: string; kind: string }[];
  links: { source: number; target: number; value: number }[];
  total: number;
  shown: number;
  basis: string;
};
export type CaseFile = {
  id: string;
  name: string;
  ids: string[];
  notes: string;
  scenarios: Simulation[];
};
export type Job = {
  timeline?: { stage: string; percent: number; elapsed: number }[];
  id: string;
  status: string;
  stage: string;
  percent: number;
  message?: string;
  cached?: boolean;
};
