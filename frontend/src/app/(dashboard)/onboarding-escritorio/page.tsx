"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Building2, Loader2, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { CnpjLookupResult } from "@/types";

const schema = z.object({
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
});
type FormData = z.infer<typeof schema>;

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

export default function OnboardingEscritorioPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [lookupLoading, setLookupLoading] = useState(false);

  const {
    register,
    handleSubmit,
    getValues,
    setValue,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const handleLookup = async () => {
    const digits = getValues("cpf_cnpj").replace(/\D/g, "");
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
      setValue("name", data.name);
      setValue("email", data.email ?? "");
      setValue("phone", data.telefone ?? "");
      toast.success("Dados do CNPJ carregados");
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao consultar CNPJ"));
    } finally {
      setLookupLoading(false);
    }
  };

  const onSubmit = async (data: FormData) => {
    setSubmitting(true);
    try {
      await api.post("/firms", { ...data, phone: data.phone || null });
      toast.success("Escritório criado");
      router.push("/dashboard");
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao criar escritório"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-8">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-2xl mb-4">
            <Building2 className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Crie seu escritório</h1>
          <p className="text-gray-500 mt-1">
            Falta só isso — depois de criado, você já pode cadastrar empresas e operadores.
          </p>
        </div>

        <div className="bg-white rounded-2xl shadow-xl p-8">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <Field label="Razão social" error={errors.name?.message}>
              <input
                {...register("name")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Meu Escritório Contábil LTDA"
              />
            </Field>
            <Field label="CPF/CNPJ" error={errors.cpf_cnpj?.message}>
              <div className="flex gap-2">
                <input
                  {...register("cpf_cnpj")}
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
                Para CNPJ, os dados são preenchidos automaticamente. Para CPF, preencha manualmente.
              </p>
            </Field>
            <Field label="E-mail" error={errors.email?.message}>
              <input
                {...register("email")}
                type="email"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="contato@meuescritorio.com.br"
              />
            </Field>
            <Field label="Telefone" error={errors.phone?.message}>
              <input
                {...register("phone")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Opcional"
              />
            </Field>

            <button
              type="submit"
              disabled={submitting}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
            >
              {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
              Criar escritório
            </button>
          </form>
        </div>
      </div>
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
