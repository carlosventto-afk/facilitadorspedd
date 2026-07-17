"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Building2, Loader2, Pencil, Plus, Power, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { CnpjLookupResult, Company } from "@/types";
import { Modal } from "@/components/ui/Modal";

const companySchema = z.object({
  name: z.string().min(2, "Nome muito curto"),
  cnpj: z
    .string()
    .min(1, "CNPJ obrigatório")
    .refine((v) => v.replace(/\D/g, "").length === 14, "CNPJ deve ter 14 dígitos"),
  uf: z.string().length(2, "UF deve ter 2 letras"),
  inscricao_estadual: z.string().optional(),
  nome_fantasia: z.string().optional(),
  cep: z.string().optional(),
  logradouro: z.string().optional(),
  numero: z.string().optional(),
  complemento: z.string().optional(),
  bairro: z.string().optional(),
  municipio: z.string().optional(),
  telefone: z.string().optional(),
  email: z.string().optional(),
});
type CompanyForm = z.infer<typeof companySchema>;

type RegistryExtra = Pick<
  CnpjLookupResult,
  "situacao_cadastral" | "natureza_juridica" | "porte" | "cnae_principal" | "cnae_descricao" | "data_abertura"
>;

const EMPTY_EXTRA: RegistryExtra = {
  situacao_cadastral: null,
  natureza_juridica: null,
  porte: null,
  cnae_principal: null,
  cnae_descricao: null,
  data_abertura: null,
};

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

function companyToFormValues(c: Company): CompanyForm {
  return {
    name: c.name,
    cnpj: c.cnpj,
    uf: c.uf,
    inscricao_estadual: c.inscricao_estadual ?? "",
    nome_fantasia: c.nome_fantasia ?? "",
    cep: c.cep ?? "",
    logradouro: c.logradouro ?? "",
    numero: c.numero ?? "",
    complemento: c.complemento ?? "",
    bairro: c.bairro ?? "",
    municipio: c.municipio ?? "",
    telefone: c.telefone ?? "",
    email: c.email ?? "",
  };
}

export default function EmpresasPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Company | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [registryExtra, setRegistryExtra] = useState<RegistryExtra>(EMPTY_EXTRA);

  const load = () => {
    setLoading(true);
    api
      .get("/firms/me/companies")
      .then((r) => {
        setCompanies(r.data);
        setLoadError(null);
      })
      .catch((err) => setLoadError(errorMessage(err, "Erro ao carregar empresas")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const createForm = useForm<CompanyForm>({
    resolver: zodResolver(companySchema),
    defaultValues: { uf: "PA" },
  });
  const editForm = useForm<CompanyForm>({ resolver: zodResolver(companySchema) });

  const applyLookupResult = (form: typeof createForm, data: CnpjLookupResult) => {
    form.setValue("name", data.name);
    form.setValue("uf", data.uf || form.getValues("uf"));
    form.setValue("nome_fantasia", data.nome_fantasia ?? "");
    form.setValue("cep", data.cep ?? "");
    form.setValue("logradouro", data.logradouro ?? "");
    form.setValue("numero", data.numero ?? "");
    form.setValue("complemento", data.complemento ?? "");
    form.setValue("bairro", data.bairro ?? "");
    form.setValue("municipio", data.municipio ?? "");
    form.setValue("telefone", data.telefone ?? "");
    form.setValue("email", data.email ?? "");
    setRegistryExtra({
      situacao_cadastral: data.situacao_cadastral,
      natureza_juridica: data.natureza_juridica,
      porte: data.porte,
      cnae_principal: data.cnae_principal,
      cnae_descricao: data.cnae_descricao,
      data_abertura: data.data_abertura,
    });
  };

  const handleLookup = async (form: typeof createForm) => {
    const digits = form.getValues("cnpj").replace(/\D/g, "");
    if (digits.length !== 14) {
      toast.error("Informe um CNPJ com 14 dígitos para buscar");
      return;
    }
    setLookupLoading(true);
    try {
      const { data } = await api.get<CnpjLookupResult>(`/firms/me/cnpj/${digits}`);
      applyLookupResult(form, data);
      toast.success("Dados do CNPJ carregados");
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao consultar CNPJ"));
    } finally {
      setLookupLoading(false);
    }
  };

  const onCreate = async (data: CompanyForm) => {
    setSubmitting(true);
    try {
      await api.post("/firms/me/companies", {
        ...data,
        uf: data.uf.toUpperCase(),
        inscricao_estadual: data.inscricao_estadual || null,
        nome_fantasia: data.nome_fantasia || null,
        cep: data.cep || null,
        logradouro: data.logradouro || null,
        numero: data.numero || null,
        complemento: data.complemento || null,
        bairro: data.bairro || null,
        municipio: data.municipio || null,
        telefone: data.telefone || null,
        email: data.email || null,
        ...registryExtra,
      });
      toast.success("Empresa cadastrada");
      setCreateOpen(false);
      createForm.reset({ uf: "PA" });
      setRegistryExtra(EMPTY_EXTRA);
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao cadastrar empresa"));
    } finally {
      setSubmitting(false);
    }
  };

  const openEdit = (company: Company) => {
    setEditing(company);
    setRegistryExtra({
      situacao_cadastral: company.situacao_cadastral,
      natureza_juridica: company.natureza_juridica,
      porte: company.porte,
      cnae_principal: company.cnae_principal,
      cnae_descricao: company.cnae_descricao,
      data_abertura: company.data_abertura,
    });
    editForm.reset(companyToFormValues(company));
  };

  const onEdit = async (data: CompanyForm) => {
    if (!editing) return;
    setSubmitting(true);
    try {
      await api.patch(`/firms/me/companies/${editing.id}`, {
        name: data.name,
        inscricao_estadual: data.inscricao_estadual || null,
        nome_fantasia: data.nome_fantasia || null,
        cep: data.cep || null,
        logradouro: data.logradouro || null,
        numero: data.numero || null,
        complemento: data.complemento || null,
        bairro: data.bairro || null,
        municipio: data.municipio || null,
        telefone: data.telefone || null,
        email: data.email || null,
        ...registryExtra,
      });
      toast.success("Empresa atualizada");
      setEditing(null);
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao atualizar empresa"));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleActive = async (company: Company) => {
    try {
      await api.patch(`/firms/me/companies/${company.id}`, { is_active: !company.is_active });
      toast.success(company.is_active ? "Empresa desativada" : "Empresa ativada");
      load();
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao atualizar status"));
    }
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Empresas</h1>
          <p className="text-gray-500 mt-1">Gerencie as empresas clientes do escritório</p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 px-4 rounded-lg transition"
        >
          <Plus className="w-4 h-4" />
          Nova empresa
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
      ) : companies.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <Building2 className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhuma empresa cadastrada ainda</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="text-left px-6 py-3 font-medium">Empresa</th>
                <th className="text-left px-6 py-3 font-medium">CNPJ</th>
                <th className="text-left px-6 py-3 font-medium">Município/UF</th>
                <th className="text-left px-6 py-3 font-medium">IE</th>
                <th className="text-left px-6 py-3 font-medium">Status</th>
                <th className="text-right px-6 py-3 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {companies.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <p className="font-medium text-gray-900">{c.name}</p>
                    {c.nome_fantasia && <p className="text-xs text-gray-400">{c.nome_fantasia}</p>}
                  </td>
                  <td className="px-6 py-4 text-gray-600">{c.cnpj}</td>
                  <td className="px-6 py-4 text-gray-600">
                    {c.municipio ? `${c.municipio}/${c.uf}` : c.uf}
                  </td>
                  <td className="px-6 py-4 text-gray-600">{c.inscricao_estadual || "—"}</td>
                  <td className="px-6 py-4">
                    <span
                      className={`text-xs font-semibold px-2.5 py-1 rounded-full ${
                        c.is_active ? "text-green-700 bg-green-50" : "text-gray-500 bg-gray-100"
                      }`}
                    >
                      {c.is_active ? "Ativa" : "Inativa"}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => openEdit(c)}
                        className="text-gray-400 hover:text-blue-600 transition-colors"
                        title="Editar"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => toggleActive(c)}
                        className={`transition-colors ${
                          c.is_active ? "text-gray-400 hover:text-red-600" : "text-gray-400 hover:text-green-600"
                        }`}
                        title={c.is_active ? "Desativar" : "Ativar"}
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
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Nova empresa"
        maxWidthClassName="max-w-2xl"
      >
        <form onSubmit={createForm.handleSubmit(onCreate)} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">CNPJ</label>
            <div className="flex gap-2">
              <input
                {...createForm.register("cnpj")}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="00.000.000/0000-00"
              />
              <button
                type="button"
                onClick={() => handleLookup(createForm)}
                disabled={lookupLoading}
                className="flex items-center gap-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 text-sm font-medium px-4 rounded-lg transition whitespace-nowrap"
              >
                {lookupLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                Buscar CNPJ
              </button>
            </div>
            {createForm.formState.errors.cnpj && (
              <p className="text-red-500 text-xs mt-1">{createForm.formState.errors.cnpj.message}</p>
            )}
          </div>

          {registryExtra.situacao_cadastral && (
            <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-0.5">
              <p>
                <span className="font-medium">Situação:</span> {registryExtra.situacao_cadastral}
                {registryExtra.porte && <> · <span className="font-medium">Porte:</span> {registryExtra.porte}</>}
              </p>
              {registryExtra.natureza_juridica && (
                <p><span className="font-medium">Natureza jurídica:</span> {registryExtra.natureza_juridica}</p>
              )}
              {registryExtra.cnae_descricao && (
                <p><span className="font-medium">Atividade principal:</span> {registryExtra.cnae_descricao}</p>
              )}
            </div>
          )}

          <CompanyFormFields form={createForm} />

          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            Cadastrar empresa
          </button>
        </form>
      </Modal>

      {/* Edit modal */}
      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title="Editar empresa"
        maxWidthClassName="max-w-2xl"
      >
        <form onSubmit={editForm.handleSubmit(onEdit)} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">CNPJ</label>
            <div className="flex gap-2">
              <input
                disabled
                value={editing?.cnpj ?? ""}
                className="flex-1 px-3 py-2 border border-gray-200 bg-gray-50 rounded-lg text-sm text-gray-500"
              />
              <button
                type="button"
                onClick={() => handleLookup(editForm)}
                disabled={lookupLoading}
                className="flex items-center gap-2 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 text-sm font-medium px-4 rounded-lg transition whitespace-nowrap"
              >
                {lookupLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                Atualizar da Receita
              </button>
            </div>
          </div>

          {registryExtra.situacao_cadastral && (
            <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-0.5">
              <p>
                <span className="font-medium">Situação:</span> {registryExtra.situacao_cadastral}
                {registryExtra.porte && <> · <span className="font-medium">Porte:</span> {registryExtra.porte}</>}
              </p>
              {registryExtra.natureza_juridica && (
                <p><span className="font-medium">Natureza jurídica:</span> {registryExtra.natureza_juridica}</p>
              )}
              {registryExtra.cnae_descricao && (
                <p><span className="font-medium">Atividade principal:</span> {registryExtra.cnae_descricao}</p>
              )}
            </div>
          )}

          <CompanyFormFields form={editForm} />

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

function CompanyFormFields({ form }: { form: ReturnType<typeof useForm<CompanyForm>> }) {
  const { register, formState } = form;
  const errors = formState.errors;
  return (
    <>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Razão social" error={errors.name?.message}>
          <input
            {...register("name")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Empresa Cliente LTDA"
          />
        </Field>
        <Field label="Nome fantasia" error={errors.nome_fantasia?.message}>
          <input
            {...register("nome_fantasia")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Opcional"
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Field label="UF" error={errors.uf?.message}>
          <input
            {...register("uf")}
            maxLength={2}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm uppercase focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="PA"
          />
        </Field>
        <Field label="Inscrição estadual" error={errors.inscricao_estadual?.message}>
          <input
            {...register("inscricao_estadual")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Opcional"
          />
        </Field>
      </div>

      <p className="text-xs font-semibold text-gray-500 uppercase pt-1">Endereço</p>
      <div className="grid grid-cols-2 gap-4">
        <Field label="CEP" error={errors.cep?.message}>
          <input
            {...register("cep")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>
        <Field label="Município" error={errors.municipio?.message}>
          <input
            {...register("municipio")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <Field label="Logradouro" error={errors.logradouro?.message}>
          <input
            {...register("logradouro")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>
        <Field label="Número" error={errors.numero?.message}>
          <input
            {...register("numero")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>
        <Field label="Complemento" error={errors.complemento?.message}>
          <input
            {...register("complemento")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>
      </div>
      <Field label="Bairro" error={errors.bairro?.message}>
        <input
          {...register("bairro")}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </Field>

      <p className="text-xs font-semibold text-gray-500 uppercase pt-1">Contato</p>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Telefone" error={errors.telefone?.message}>
          <input
            {...register("telefone")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>
        <Field label="E-mail" error={errors.email?.message}>
          <input
            {...register("email")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </Field>
      </div>
    </>
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
