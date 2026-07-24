"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Loader2, Pencil, Plus, Power, Users } from "lucide-react";
import { api } from "@/lib/api";
import type { AccountingFirm, OperatorUser } from "@/types";
import { Modal } from "@/components/ui/Modal";

const ROLE_LABELS: Record<string, string> = {
  ADMIN: "Admin",
  GESTOR: "Gestor",
  OPERADOR: "Operador",
};

const createSchema = z
  .object({
    full_name: z.string().min(2, "Nome muito curto"),
    email: z.string().email("E-mail inválido"),
    password: z.string().min(8, "Senha deve ter no mínimo 8 caracteres"),
    role: z.enum(["ADMIN", "GESTOR", "OPERADOR"]),
    accounting_firm_id: z.string().optional(),
  })
  .refine((data) => data.role !== "OPERADOR" || !!data.accounting_firm_id, {
    // Gestor pode ser cadastrado sem escritório — ele cria o dele depois
    // (ver /onboarding-escritorio). Operador não faz sentido sem escritório.
    message: "Escritório obrigatório para Operador",
    path: ["accounting_firm_id"],
  });
type CreateForm = z.infer<typeof createSchema>;

const editSchema = z.object({
  full_name: z.string().min(2, "Nome muito curto"),
});
type EditForm = z.infer<typeof editSchema>;

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

export default function AdminUsuariosPage() {
  const [users, setUsers] = useState<OperatorUser[]>([]);
  const [firms, setFirms] = useState<AccountingFirm[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<OperatorUser | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([api.get("/admin/users"), api.get("/admin/accounting-firms")])
      .then(([usersRes, firmsRes]) => {
        setUsers(usersRes.data);
        setFirms(firmsRes.data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(errorMessage(err, "Erro ao carregar usuários")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const firmNameById = new Map(firms.map((f) => [f.id, f.name]));

  const createForm = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { role: "OPERADOR" },
  });
  const editForm = useForm<EditForm>({ resolver: zodResolver(editSchema) });

  const onCreate = async (data: CreateForm) => {
    setSubmitting(true);
    try {
      await api.post("/admin/users", {
        ...data,
        accounting_firm_id: data.accounting_firm_id || null,
      });
      toast.success("Usuário cadastrado");
      setCreateOpen(false);
      createForm.reset({ role: "OPERADOR" });
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao cadastrar usuário"));
    } finally {
      setSubmitting(false);
    }
  };

  const openEdit = (user: OperatorUser) => {
    setEditing(user);
    editForm.reset({ full_name: user.full_name });
  };

  const onEdit = async (data: EditForm) => {
    if (!editing) return;
    setSubmitting(true);
    try {
      await api.patch(`/admin/users/${editing.id}`, data);
      toast.success("Usuário atualizado");
      setEditing(null);
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao atualizar usuário"));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleActive = async (user: OperatorUser) => {
    try {
      await api.patch(`/admin/users/${user.id}`, { is_active: !user.is_active });
      toast.success(user.is_active ? "Usuário desativado" : "Usuário ativado");
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao atualizar status"));
    }
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Usuários</h1>
          <p className="text-gray-500 mt-1">Todos os usuários de todos os escritórios</p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 px-4 rounded-lg transition"
        >
          <Plus className="w-4 h-4" />
          Novo usuário
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
      ) : users.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <Users className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhum usuário cadastrado ainda</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="text-left px-6 py-3 font-medium">Nome</th>
                <th className="text-left px-6 py-3 font-medium">E-mail</th>
                <th className="text-left px-6 py-3 font-medium">Papel</th>
                <th className="text-left px-6 py-3 font-medium">Escritório</th>
                <th className="text-left px-6 py-3 font-medium">Status</th>
                <th className="text-right px-6 py-3 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 font-medium text-gray-900">{u.full_name}</td>
                  <td className="px-6 py-4 text-gray-600">{u.email}</td>
                  <td className="px-6 py-4">
                    <span className="text-xs font-semibold px-2.5 py-1 rounded-full text-indigo-700 bg-indigo-50">
                      {ROLE_LABELS[u.role] ?? u.role}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-600">
                    {u.accounting_firm_id ? firmNameById.get(u.accounting_firm_id) ?? "—" : "—"}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`text-xs font-semibold px-2.5 py-1 rounded-full ${
                        u.is_active ? "text-green-700 bg-green-50" : "text-gray-500 bg-gray-100"
                      }`}
                    >
                      {u.is_active ? "Ativo" : "Inativo"}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => openEdit(u)}
                        className="text-gray-400 hover:text-blue-600 transition-colors"
                        title="Editar"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => toggleActive(u)}
                        className={`transition-colors ${
                          u.is_active ? "text-gray-400 hover:text-red-600" : "text-gray-400 hover:text-green-600"
                        }`}
                        title={u.is_active ? "Desativar" : "Ativar"}
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
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Novo usuário">
        <form onSubmit={createForm.handleSubmit(onCreate)} className="space-y-4">
          <Field label="Nome completo" error={createForm.formState.errors.full_name?.message}>
            <input
              {...createForm.register("full_name")}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </Field>
          <Field label="E-mail" error={createForm.formState.errors.email?.message}>
            <input
              {...createForm.register("email")}
              type="email"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </Field>
          <Field label="Senha provisória" error={createForm.formState.errors.password?.message}>
            <input
              {...createForm.register("password")}
              type="password"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Mínimo 8 caracteres"
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Papel" error={createForm.formState.errors.role?.message}>
              <select
                {...createForm.register("role")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option value="OPERADOR">Operador</option>
                <option value="GESTOR">Gestor</option>
                <option value="ADMIN">Admin</option>
              </select>
            </Field>
            <Field
              label="Escritório"
              error={createForm.formState.errors.accounting_firm_id?.message}
            >
              <select
                {...createForm.register("accounting_firm_id")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option value="">Nenhum</option>
                {firms.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            Cadastrar usuário
          </button>
        </form>
      </Modal>

      {/* Edit modal */}
      <Modal open={!!editing} onClose={() => setEditing(null)} title="Editar usuário">
        <form onSubmit={editForm.handleSubmit(onEdit)} className="space-y-4">
          <Field label="Nome completo" error={editForm.formState.errors.full_name?.message}>
            <input
              {...editForm.register("full_name")}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </Field>
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
