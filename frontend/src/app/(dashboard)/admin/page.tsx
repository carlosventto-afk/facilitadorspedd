"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AdminStats } from "@/types";
import { Building2, CheckCircle2, FileText, Loader2, Users, XCircle } from "lucide-react";

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AdminStats>("/admin/stats")
      .then((r) => setStats(r.data))
      .catch((err) => setLoadError(errorMessage(err, "Erro ao carregar estatísticas")))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Painel Admin</h1>
        <p className="text-gray-500 mt-1">Visão geral de todos os escritórios da plataforma</p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-8 text-center text-red-600">
          {loadError}
        </div>
      ) : (
        stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
            <StatCard
              icon={<Building2 className="w-5 h-5 text-blue-600" />}
              label="Escritórios"
              value={stats.total_accounting_firms}
            />
            <StatCard
              icon={<CheckCircle2 className="w-5 h-5 text-green-600" />}
              label="Assinaturas ativas"
              value={stats.active_subscriptions}
            />
            <StatCard
              icon={<FileText className="w-5 h-5 text-purple-600" />}
              label="Jobs processados"
              value={stats.total_jobs_processed}
            />
            <StatCard
              icon={<XCircle className="w-5 h-5 text-red-600" />}
              label="Jobs com falha"
              value={stats.failed_jobs}
            />
          </div>
        )
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <QuickAction
          href="/admin/escritorios"
          icon={<Building2 className="w-6 h-6 text-indigo-600" />}
          title="Escritórios"
          desc="Gerenciar escritórios contábeis e assinaturas"
          color="bg-indigo-50"
        />
        <QuickAction
          href="/admin/usuarios"
          icon={<Users className="w-6 h-6 text-purple-600" />}
          title="Usuários"
          desc="Gerenciar usuários de todos os escritórios"
          color="bg-purple-50"
        />
      </div>
    </div>
  );
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-2">{icon}</div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
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
