"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Mail } from "lucide-react";
import { api } from "@/lib/api";
import type { AccountingFirm, Company, SubscriptionPlan } from "@/types";
import { cn } from "@/lib/utils";

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

const PLAN_LABELS: Record<SubscriptionPlan, string> = {
  STARTER: "Starter",
  PROFESSIONAL: "Professional",
  ENTERPRISE: "Enterprise",
};

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  ACTIVE: { label: "Ativa", color: "text-green-700 bg-green-50" },
  TRIALING: { label: "Período de teste", color: "text-blue-700 bg-blue-50" },
  PAST_DUE: { label: "Pagamento pendente", color: "text-red-700 bg-red-50" },
  CANCELED: { label: "Cancelada", color: "text-gray-600 bg-gray-100" },
};

const PLANS: {
  id: SubscriptionPlan;
  price: string;
  companies: string;
  jobs: string;
  highlight?: boolean;
}[] = [
  { id: "STARTER", price: "R$ 97/mês", companies: "até 5 empresas", jobs: "até 20 jobs/mês" },
  {
    id: "PROFESSIONAL",
    price: "R$ 247/mês",
    companies: "até 30 empresas",
    jobs: "até 150 jobs/mês",
    highlight: true,
  },
  { id: "ENTERPRISE", price: "R$ 597/mês", companies: "empresas ilimitadas", jobs: "jobs ilimitados" },
];

export default function AssinaturaPage() {
  const [firm, setFirm] = useState<AccountingFirm | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.get("/firms/me"), api.get("/firms/me/companies")])
      .then(([firmRes, companiesRes]) => {
        setFirm(firmRes.data);
        setCompanies(companiesRes.data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(errorMessage(err, "Erro ao carregar assinatura")))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center py-16 text-gray-400">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="p-8">
        <div className="bg-white rounded-xl border border-red-200 p-8 text-center text-red-600">
          {loadError}
        </div>
      </div>
    );
  }

  const sub = firm?.subscription;
  const activeCompanies = companies.filter((c) => c.is_active).length;
  const status = sub ? STATUS_LABELS[sub.status] ?? { label: sub.status, color: "text-gray-600 bg-gray-100" } : null;

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Assinatura</h1>
        <p className="text-gray-500 mt-1">Plano atual e dados do escritório</p>
      </div>

      {/* Firm info */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <h2 className="font-semibold text-gray-800 mb-4">Escritório</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-500">Razão social</p>
            <p className="font-medium text-gray-900">{firm?.name}</p>
          </div>
          <div>
            <p className="text-gray-500">CNPJ</p>
            <p className="font-medium text-gray-900">{firm?.cnpj}</p>
          </div>
          <div>
            <p className="text-gray-500">E-mail</p>
            <p className="font-medium text-gray-900">{firm?.email}</p>
          </div>
          <div>
            <p className="text-gray-500">Telefone</p>
            <p className="font-medium text-gray-900">{firm?.phone || "—"}</p>
          </div>
        </div>
      </div>

      {/* Current plan */}
      {sub && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-sm text-gray-500">Plano atual</p>
              <p className="text-xl font-bold text-gray-900">{PLAN_LABELS[sub.plan] ?? sub.plan}</p>
            </div>
            {status && (
              <span className={`text-xs font-semibold px-3 py-1 rounded-full ${status.color}`}>
                {status.label}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="bg-gray-50 rounded-lg p-4">
              <p className="text-gray-500">Empresas</p>
              <p className="text-lg font-semibold text-gray-900">
                {activeCompanies} <span className="text-gray-400 font-normal">/ {sub.max_companies}</span>
              </p>
            </div>
            <div className="bg-gray-50 rounded-lg p-4">
              <p className="text-gray-500">Jobs por mês</p>
              <p className="text-lg font-semibold text-gray-900">até {sub.max_jobs_per_month}</p>
            </div>
          </div>
        </div>
      )}

      {/* Plans comparison */}
      <h2 className="font-semibold text-gray-800 mb-4">Planos disponíveis</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        {PLANS.map((plan) => {
          const isCurrent = sub?.plan === plan.id;
          return (
            <div
              key={plan.id}
              className={cn(
                "bg-white rounded-xl border p-6",
                isCurrent ? "border-blue-500 ring-1 ring-blue-500" : "border-gray-200"
              )}
            >
              <div className="flex items-center gap-2 mb-1">
                <p className="font-semibold text-gray-900">{PLAN_LABELS[plan.id]}</p>
                {isCurrent && <CheckCircle2 className="w-4 h-4 text-blue-600" />}
              </div>
              <p className="text-2xl font-bold text-gray-900 mb-4">{plan.price}</p>
              <ul className="text-sm text-gray-600 space-y-1.5 mb-6">
                <li>{plan.companies}</li>
                <li>{plan.jobs}</li>
              </ul>
              {isCurrent ? (
                <div className="text-center text-sm font-medium text-blue-600 py-2">
                  Plano atual
                </div>
              ) : (
                <a
                  href="mailto:contato@facilitadorsped.com.br?subject=Alteração de plano"
                  className="flex items-center justify-center gap-2 w-full text-sm font-medium text-gray-700 border border-gray-300 hover:bg-gray-50 py-2 rounded-lg transition"
                >
                  <Mail className="w-4 h-4" />
                  Fale conosco
                </a>
              )}
            </div>
          );
        })}
      </div>
      <p className="text-xs text-gray-400 text-center">
        A alteração de plano ainda é feita manualmente pelo nosso time — em breve o self-service estará disponível aqui.
      </p>
    </div>
  );
}
