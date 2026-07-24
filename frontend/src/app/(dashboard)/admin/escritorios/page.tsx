"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Building2, Loader2, Pencil, Plus, Power, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { AccountingFirm, CnpjLookupResult, SubscriptionPlan } from "@/types";
import { Modal } from "@/components/ui/Modal";

const PLAN_LABELS: Record<SubscriptionPlan, string> = {
  STARTER: "Starter",
  PROFESSIONAL: "Professional",
  ENTERPRISE: "Enterprise",
};

const STATUS_COLORS: Record<string, string> = {
  ACTIVE: "text-green-700 bg-green-50",
  TRIALING: "text-blue-700 bg-blue-50",
  PAST_DUE: "text-red-700 bg-red-50",
  CANCELED: "text-gray-600 bg-gray-100",
};

const createSchema = z.object({
  name: z.string().min(2, "Nome muito curto"),
  cpf_cnpj: z
    .string()
    .min(1, "CPF ou CNPJ obrigatório")
    .refine(
      (v) => [11, 14].includes(v.replace(/\D/g, "").length),
      "Informe um CPF (11 dígitos) ou CNPJ (14 dígitos)"
    ),
  email: z.string().email("E-mail inválido"),
  phone: z.string().optional(),
  plan: z.enum(["STARTER", "PROFESSIONAL", "ENTERPRISE"]),
});
type CreateForm = z.infer<typeof createSchema>;

const editSchema = z.object({
  name: z.string().min(2, "Nome muito curto"),
  email: z.string().email("E-mail inválido"),
  phone: z.string().optional(),
  plan: z.enum(["STARTER", "PROFESSIONAL", "ENTERPRISE"]),
});
type EditForm = z.infer<typeof editSchema>;

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

export default function AdminEscritoriosPage() {
  const [firms, setFirms] = useState<AccountingFirm[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<AccountingFirm | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [lookupLoading, setLookupLoading] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .get("/admin/accounting-firms")
      .then((r) => {
        setFirms(r.data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(errorMessage(err, "Erro ao carregar escritórios")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const createForm = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { plan: "STARTER" },
  });
  const editForm = useForm<EditForm>({ resolver: zodResolver(editSchema) });

  const handleLookup = async () => {
    const digits = createForm.getValues("cpf_cnpj").replace(/\D/g, "");
    if (digits.length === 11) {
      toast.error("Consulta automática disponível só para CNPJ — preencha os dados do CPF manualmente");
      return;
    }
    if (digits.length !== 14) {
      toast.error("Informe um CNPJ com 14 dígitos para buscar");
      return;
    }
    setLookupLoading(true);
    try {
      const { data } = await api.get<CnpjLookupResult>(`/firms/me/cnpj/${digits}`);
      createForm.setValue("name", data.name);
      createForm.setValue("email", data.email ?? "");
      createForm.setValue("phone", data.telefone ?? "");
      toast.success("Dados do CNPJ carregados");
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao consultar CNPJ"));
    } finally {
      setLookupLoading(false);
    }
  };

  const onCreate = async (data: CreateForm) => {
    setSubmitting(true);
    try {
      await api.post("/admin/accounting-firms", data);
      toast.success("Escritório cadastrado");
      setCreateOpen(false);
      createForm.reset({ plan: "STARTER" });
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao cadastrar escritório"));
    } finally {
      setSubmitting(false);
    }
  };

  const openEdit = (firm: AccountingFirm) => {
    setEditing(firm);
    editForm.reset({
      name: firm.name,
      email: firm.email,
      phone: firm.phone ?? "",
      plan: firm.subscription?.plan ?? "STARTER",
    });
  };

  const onEdit = async (data: EditForm) => {
    if (!editing) return;
    setSubmitting(true);
    try {
      await api.patch(`/admin/accounting-firms/${editing.id}`, {
        ...data,
        phone: data.phone || null,
      });
      toast.success("Escritório atualizado");
      setEditing(null);
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao atualizar escritório"));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleActive = async (firm: AccountingFirm) => {
    try {
      await api.patch(`/admin/accounting-firms/${firm.id}`, { is_active: !firm.is_active });
      toast.success(firm.is_active ? "Escritório desativado" : "Escritório ativado");
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao atualizar status"));
    }
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Escritórios</h1>
          <p className="text-gray-500 mt-1">Todos os escritórios contábeis da plataforma</p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 px-4 rounded-lg transition"
        >
          <Plus className="w-4 h-4" />
          Novo escritório
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
      ) : firms.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <Building2 className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhum escritório cadastrado ainda</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="text-left px-6 py-3 font-medium">Escritório</th>
                <th className="text-left px-6 py-3 font-medium">CPF/CNPJ</th>
                <th className="text-left px-6 py-3 font-medium">Plano</th>
                <th className="text-left px-6 py-3 font-medium">Assinatura</th>
                <th className="text-left px-6 py-3 font-medium">Limites</th>
                <th className="text-left px-6 py-3 font-medium">Status</th>
                <th className="text-right px-6 py-3 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {firms.map((f) => (
                <tr key={f.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <p className="font-medium text-gray-900">{f.name}</p>
                    <p className="text-xs text-gray-400">{f.email}</p>
                  </td>
                  <td className="px-6 py-4 text-gray-600">{f.cpf_cnpj}</td>
                  <td className="px-6 py-4 text-gray-600">
                    {f.subscription ? PLAN_LABELS[f.subscription.plan] : "—"}
                  </td>
                  <td className="px-6 py-4">
                    {f.subscription && (
                      <span
                        className={`text-xs font-semibold px-2.5 py-1 rounded-full ${
                          STATUS_COLORS[f.subscription.status] ?? "text-gray-600 bg-gray-100"
                        }`}
                      >
                        {f.subscription.status}
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-gray-600 text-xs">
                    {f.subscription
                      ? `${f.subscription.max_companies} emp. / ${f.subscription.max_jobs_per_month} jobs`
                      : "—"}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`text-xs font-semibold px-2.5 py-1 rounded-full ${
                        f.is_active ? "text-green-700 bg-green-50" : "text-gray-500 bg-gray-100"
                      }`}
                    >
                      {f.is_active ? "Ativo" : "Inativo"}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => openEdit(f)}
                        className="text-gray-400 hover:text-blue-600 transition-colors"
                        title="Editar"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => toggleActive(f)}
                        className={`transition-colors ${
                          f.is_active ? "text-gray-400 hover:text-red-600" : "text-gray-400 hover:text-green-600"
                        }`}
                        title={f.is_active ? "Desativar" : "Ativar"}
                      >
                        <Power className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Novo escritório">
        <form onSubmit={createForm.handleSubmit(onCreate)} className="space-y-4">
          <Field label="Razão social" error={createForm.formState.errors.name?.message}>
            <input
              {...createForm.register("name")}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Escritório Contábil LTDA"
            />
          </Field>
          <Field label="CPF/CNPJ" error={createForm.formState.errors.cpf_cnpj?.message}>
            <div className="flex gap-2">
              <input
                {...createForm.register("cpf_cnpj")}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="CNPJ ou CPF"
              />
              <button
                type="button"
                onClick={handleLookup}
                disabled={lookupLoading}
                className="flex items-center gap-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 text-sm font-medium px-4 rounded-lg transition whitespace-nowrap"
              >
                {lookupLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                Buscar CNPJ
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              Para CNPJ, os dados são preenchidos automaticamente pela Receita Federal. Para CPF, preencha manualmente.
            </p>
          </Field>
          <Field label="E-mail" error={createForm.formState.errors.email?.message}>
            <input
              {...createForm.register("email")}
              type="email"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Telefone" error={createForm.formState.errors.phone?.message}>
              <input
                {...createForm.register("phone")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Opcional"
              />
            </Field>
            <Field label="Plano" error={createForm.formState.errors.plan?.message}>
              <select
                {...createForm.register("plan")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option value="STARTER">Starter</option>
                <option value="PROFESSIONAL">Professional</option>
                <option value="ENTERPRISE">Enterprise</option>
              </select>
            </Field>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            Cadastrar escritório
          </button>
        </form>
      </Modal>

      {/* Edit modal */}
      <Modal open={!!editing} onClose={() => setEditing(null)} title="Editar escritório">
        <form onSubmit={editForm.handleSubmit(onEdit)} className="space-y-4">
          <Field label="Razão social" error={editForm.formState.errors.name?.message}>
            <input
              {...editForm.register("name")}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </Field>
          <Field label="E-mail" error={editForm.formState.errors.email?.message}>
            <input
              {...editForm.register("email")}
              type="email"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Telefone" error={editForm.formState.errors.phone?.message}>
              <input
                {...editForm.register("phone")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Opcional"
              />
            </Field>
            <Field label="Plano" error={editForm.formState.errors.plan?.message}>
              <select
                {...editForm.register("plan")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option value="STARTER">Starter</option>
                <option value="PROFESSIONAL">Professional</option>
                <option value="ENTERPRISE">Enterprise</option>
              </select>
            </Field>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            Salvar alterações
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
