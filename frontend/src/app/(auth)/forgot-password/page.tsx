"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { CheckCircle2, FileText, Loader2 } from "lucide-react";

const schema = z.object({
  email: z.string().email("E-mail inválido"),
});
type FormData = z.infer<typeof schema>;

export default function ForgotPasswordPage() {
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    setLoading(true);
    try {
      await api.post("/auth/forgot-password", data);
      setSent(true);
    } catch {
      // Backend sempre responde 204 independente do e-mail existir — um erro
      // aqui é falha de rede/servidor, não "e-mail não encontrado".
      toast.error("Erro ao solicitar redefinição de senha. Tente novamente.");
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
          {sent ? (
            <div className="text-center space-y-4">
              <CheckCircle2 className="w-12 h-12 text-green-600 mx-auto" />
              <h2 className="text-xl font-semibold text-gray-800">Verifique seu e-mail</h2>
              <p className="text-sm text-gray-500">
                Se esse e-mail estiver cadastrado, enviamos um link para redefinir sua senha.
                O link expira em 30 minutos.
              </p>
              <a href="/login" className="inline-block text-sm text-blue-600 hover:underline">
                Voltar para o login
              </a>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-semibold text-gray-800 mb-2">Esqueci minha senha</h2>
              <p className="text-sm text-gray-500 mb-6">
                Informe seu e-mail e enviaremos um link para redefinir sua senha.
              </p>

              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">E-mail</label>
                  <input
                    {...register("email")}
                    type="email"
                    autoComplete="email"
                    placeholder="contador@escritorio.com.br"
                    className="w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                  />
                  {errors.email && (
                    <p className="text-red-500 text-xs mt-1">{errors.email.message}</p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-2.5 px-4 rounded-lg transition"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {loading ? "Enviando..." : "Enviar link de redefinição"}
                </button>

                <a
                  href="/login"
                  className="block text-center text-sm text-gray-500 hover:text-gray-700 mt-2"
                >
                  Voltar para o login
                </a>
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
