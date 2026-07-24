"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Building2, CheckCircle2, FileText, Upload } from "lucide-react";
import type { UserProfile, AccountingFirm } from "@/types";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [firm, setFirm] = useState<AccountingFirm | null>(null);

  useEffect(() => {
    api.get("/auth/me").then((r) => {
      setUser(r.data);
      if (r.data.role === "ADMIN") {
        router.replace("/admin");
        return;
      }
      api
        .get("/firms/me")
        .then((fr) => setFirm(fr.data))
        .catch((err) => {
          // Gestor sem escritório ainda (ex. cadastrado direto pelo Admin
          // sem escolher um) — cria o dele antes de usar o resto do painel.
          if (r.data.role === "GESTOR" && err?.response?.status === 404) {
            router.replace("/onboarding-escritorio");
          }
        });
    });
  }, [router]);

  const planLabels: Record<string, string> = {
    STARTER: "Starter",
    PROFESSIONAL: "Professional",
    ENTERPRISE: "Enterprise",
  };
  const statusColors: Record<string, string> = {
    ACTIVE: "text-green-600 bg-green-50",
    TRIALING: "text-blue-600 bg-blue-50",
    PAST_DUE: "text-red-600 bg-red-50",
    CANCELED: "text-gray-600 bg-gray-50",
  };

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">
          Olá, {user?.full_name?.split(" ")[0] ?? "..."}
        </h1>
        <p className="text-gray-500 mt-1">Bem-vindo ao FacilitadorSped</p>
      </div>

      {/* Subscription card */}
      {firm?.subscription && (
        <div className="mb-8 bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Plano atual</p>
              <p className="text-xl font-bold text-gray-900">
                {planLabels[firm.subscription.plan] ?? firm.subscription.plan}
              </p>
            </div>
            <span
              className={`text-xs font-semibold px-3 py-1 rounded-full ${
                statusColors[firm.subscription.status] ?? "text-gray-600 bg-gray-50"
              }`}
            >
              {firm.subscription.status}
            </span>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4 text-sm text-gray-600">
            <div>Empresas: até {firm.subscription.max_companies}</div>
            <div>Jobs/mês: até {firm.subscription.max_jobs_per_month}</div>
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <QuickAction
          href="/processar"
          icon={<Upload className="w-6 h-6 text-blue-600" />}
          title="Processar SPED"
          desc="Upload do arquivo SPED + planilha SEFA-PA"
          color="bg-blue-50"
        />
        <QuickAction
          href="/empresas"
          icon={<Building2 className="w-6 h-6 text-indigo-600" />}
          title="Empresas"
          desc="Gerenciar empresas clientes"
          color="bg-indigo-50"
        />
        <QuickAction
          href="/usuarios"
          icon={<FileText className="w-6 h-6 text-purple-600" />}
          title="Usuários"
          desc="Convidar e gerenciar operadores"
          color="bg-purple-50"
        />
      </div>
    </div>
  );
}

function QuickAction({
  href,
  icon,
  title,
  desc,
  color,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  desc: string;
  color: string;
}) {
  return (
    <a
      href={href}
      className="bg-white rounded-xl border border-gray-200 p-6 hover:shadow-md transition-shadow block"
    >
      <div className={`w-12 h-12 ${color} rounded-lg flex items-center justify-center mb-4`}>
        {icon}
      </div>
      <p className="font-semibold text-gray-900">{title}</p>
      <p className="text-sm text-gray-500 mt-1">{desc}</p>
    </a>
  );
}
