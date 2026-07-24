"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Loader2, Mail, Plus, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { AccountingFirm, Invitation, InvitationStatus } from "@/types";
import { Modal } from "@/components/ui/Modal";

const STATUS_LABELS: Record<InvitationStatus, string> = {
  PENDING: "Pendente",
  ACCEPTED: "Aceito",
  CANCELED: "Cancelado",
};

const STATUS_COLORS: Record<InvitationStatus, string> = {
  PENDING: "text-blue-700 bg-blue-50",
  ACCEPTED: "text-green-700 bg-green-50",
  CANCELED: "text-gray-600 bg-gray-100",
};

const createSchema = z.object({
  email: z.string().email("E-mail inválido"),
  accounting_firm_id: z.string().min(1, "Escritório obrigatório"),
});
type CreateForm = z.infer<typeof createSchema>;

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR");
}

export default function AdminConvitesPage() {
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [firms, setFirms] = useState<AccountingFirm[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([api.get("/admin/invitations"), api.get("/admin/accounting-firms")])
      .then(([invitesRes, firmsRes]) => {
        setInvitations(invitesRes.data);
        setFirms(firmsRes.data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(errorMessage(err, "Erro ao carregar convites")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const firmNameById = new Map(firms.map((f) => [f.id, f.name]));

  const createForm = useForm<CreateForm>({ resolver: zodResolver(createSchema) });

  const onCreate = async (data: CreateForm) => {
    setSubmitting(true);
    try {
      await api.post("/admin/invitations", data);
      toast.success("Convite enviado");
      setCreateOpen(false);
      createForm.reset();
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao enviar convite"));
    } finally {
      setSubmitting(false);
    }
  };

  const cancelInvitation = async (invitation: Invitation) => {
    try {
      await api.delete(`/admin/invitations/${invitation.id}`);
      toast.success("Convite cancelado");
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao cancelar convite"));
    }
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Convites</h1>
          <p className="text-gray-500 mt-1">Convide Gestores para um escritório por e-mail</p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 px-4 rounded-lg transition"
        >
          <Plus className="w-4 h-4" />
          Novo convite
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 p-8 text-center text-red-600">
          {loadError}
        </div>
      ) : invitations.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <Mail className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhum convite enviado ainda</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="text-left px-6 py-3 font-medium">E-mail</th>
                <th className="text-left px-6 py-3 font-medium">Escritório</th>
                <th className="text-left px-6 py-3 font-medium">Status</th>
                <th className="text-left px-6 py-3 font-medium">Convidado em</th>
                <th className="text-right px-6 py-3 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {invitations.map((i) => (
                <tr key={i.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 font-medium text-gray-900">{i.email}</td>
                  <td className="px-6 py-4 text-gray-600">
                    {firmNameById.get(i.accounting_firm_id) ?? "—"}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`text-xs font-semibold px-2.5 py-1 rounded-full ${STATUS_COLORS[i.status]}`}
                    >
                      {STATUS_LABELS[i.status]}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-600">{formatDate(i.created_at)}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-3">
                      {i.status === "PENDING" && (
                        <button
                          onClick={() => cancelInvitation(i)}
                          className="text-gray-400 hover:text-red-600 transition-colors"
                          title="Cancelar convite"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Novo convite">
        <form onSubmit={createForm.handleSubmit(onCreate)} className="space-y-4">
          <Field label="E-mail" error={createForm.formState.errors.email?.message}>
            <input
              {...createForm.register("email")}
              type="email"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="gestor@escritorio.com.br"
            />
          </Field>
          <Field
            label="Escritório"
            error={createForm.formState.errors.accounting_firm_id?.message}
          >
            <select
              {...createForm.register("accounting_firm_id")}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Selecione um escritório</option>
              {firms.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            Enviar convite
          </button>
        </form>
      </Modal>
    </div>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
    </div>
  );
}
