"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Building2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

const schema = z.object({
  name: z.string().min(2, "Nome muito curto"),
  cnpj: z
    .string()
    .min(1, "CNPJ obrigatório")
    .refine((v) => v.replace(/\D/g, "").length === 14, "CNPJ deve ter 14 dígitos"),
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

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

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
            <Field label="CNPJ" error={errors.cnpj?.message}>
              <input
                {...register("cnpj")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="00.000.000/0000-00"
              />
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
