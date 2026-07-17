"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { FileText, Loader2, XCircle } from "lucide-react";

const schema = z
  .object({
    new_password: z.string().min(8, "A senha deve ter no mínimo 8 caracteres"),
    confirm_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: "As senhas não coincidem",
    path: ["confirm_password"],
  });
type FormData = z.infer<typeof schema>;

function errorMessage(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  );
}

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [loading, setLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    if (!token) return;
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: data.new_password });
      toast.success("Senha redefinida com sucesso. Faça login com a nova senha.");
      router.push("/login");
    } catch (err) {
      toast.error(errorMessage(err, "Erro ao redefinir senha"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-2xl mb-4">
            <FileText className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900">FacilitadorSped</h1>
          <p className="text-gray-500 mt-1">Automação de ICMS Antecipado — Pará</p>
        </div>

        <div className="bg-white rounded-2xl shadow-xl p-8">
          {!token ? (
            <div className="text-center space-y-4">
              <XCircle className="w-12 h-12 text-red-500 mx-auto" />
              <h2 className="text-xl font-semibold text-gray-800">Link inválido</h2>
              <p className="text-sm text-gray-500">
                Este link de redefinição de senha é inválido. Solicite um novo.
              </p>
              <a
                href="/forgot-password"
                className="inline-block text-sm text-blue-600 hover:underline"
              >
                Solicitar novo link
              </a>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-semibold text-gray-800 mb-6">Redefinir senha</h2>

              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Nova senha
                  </label>
                  <input
                    {...register("new_password")}
                    type="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    className="w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                  />
                  {errors.new_password && (
                    <p className="text-red-500 text-xs mt-1">{errors.new_password.message}</p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Confirmar nova senha
                  </label>
                  <input
                    {...register("confirm_password")}
                    type="password"
                    autoComplete="new-password"
                    placeholder="••••••••"
                    className="w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                  />
                  {errors.confirm_password && (
                    <p className="text-red-500 text-xs mt-1">{errors.confirm_password.message}</p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {loading ? "Salvando..." : "Redefinir senha"}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-sm text-gray-500 mt-6">
          FacilitadorSped &copy; {new Date().getFullYear()}
        </p>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
