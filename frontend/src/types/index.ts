export type UserRole = "ADMIN" | "GESTOR" | "OPERADOR";
export type SubscriptionPlan = "STARTER" | "PROFESSIONAL" | "ENTERPRISE";
export type SubscriptionStatus = "TRIALING" | "ACTIVE" | "PAST_DUE" | "CANCELED";
export type JobStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
export type TipoAntecipacao = "NORMAL" | "ESPECIAL" | "CESTA_BASICA";
export type InvitationStatus = "PENDING" | "ACCEPTED" | "CANCELED";

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
  cpf_cnpj: string;
  email: string;
  phone: string | null;
  is_active: boolean;
  subscription: Subscription | null;
}

export interface AdminStats {
  total_accounting_firms: number;
  active_subscriptions: number;
  total_jobs_processed: number;
  failed_jobs: number;
}

export interface CnpjRegistryData {
  nome_fantasia: string | null;
  situacao_cadastral: string | null;
  data_abertura: string | null;
  natureza_juridica: string | null;
  porte: string | null;
  cnae_principal: string | null;
  cnae_descricao: string | null;
  telefone: string | null;
  email: string | null;
  cep: string | null;
  logradouro: string | null;
  numero: string | null;
  complemento: string | null;
  bairro: string | null;
  municipio: string | null;
}

export interface Company extends CnpjRegistryData {
  id: string;
  accounting_firm_id: string;
  name: string;
  cnpj: string;
  inscricao_estadual: string | null;
  uf: string;
  is_active: boolean;
}

export interface CnpjLookupResult extends CnpjRegistryData {
  name: string;
  uf: string;
}

export interface Invitation {
  id: string;
  email: string;
  accounting_firm_id: string;
  status: InvitationStatus;
  invited_by: string | null;
  accepted_at: string | null;
  created_user_id: string | null;
  created_at: string;
}

export interface OperatorUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  accounting_firm_id: string | null;
}

export interface JobLogEntry {
  level: "INFO" | "WARN" | "ERROR";
  message: string;
  created_at: string;
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
