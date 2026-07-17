export type UserRole = "ADMIN" | "GESTOR" | "OPERADOR";
export type SubscriptionPlan = "STARTER" | "PROFESSIONAL" | "ENTERPRISE";
export type SubscriptionStatus = "TRIALING" | "ACTIVE" | "PAST_DUE" | "CANCELED";
export type JobStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
export type TipoAntecipacao = "NORMAL" | "ESPECIAL" | "CESTA_BASICA";

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  accounting_firm_id: string | null;
}

export interface Subscription {
  id: string;
  plan: SubscriptionPlan;
  status: SubscriptionStatus;
  max_companies: number;
  max_jobs_per_month: number;
}

export interface AccountingFirm {
  id: string;
  name: string;
  cnpj: string;
  email: string;
  phone: string | null;
  subscription: Subscription | null;
}

export interface Company {
  id: string;
  accounting_firm_id: string;
  name: string;
  cnpj: string;
  inscricao_estadual: string | null;
  uf: string;
  is_active: boolean;
}

export interface ProcessingJob {
  id: string;
  company_id: string;
  status: JobStatus;
  period_start: string;
  period_end: string;
  nfs_found: number | null;
  anticipations_matched: number | null;
  anticipations_total: number | null;
  c197_records_inserted: number | null;
  e111_records_inserted: number | null;
  e116_records_inserted: number | null;
  error_message: string | null;
  created_at: string;
  processing_started_at: string | null;
  processing_finished_at: string | null;
}
