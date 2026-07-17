"use client";

import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Company, ProcessingJob } from "@/types";
import {
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Upload,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Step = "form" | "processing" | "done" | "error";

export default function ProcessarPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedCompany, setSelectedCompany] = useState("");
  const [competencia, setCompetencia] = useState(""); // "YYYY-MM"
  const [spedFile, setSpedFile] = useState<File | null>(null);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>("form");
  const [job, setJob] = useState<ProcessingJob | null>(null);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    api.get("/firms/me/companies").then((r) => setCompanies(r.data));
  }, []);

  // Poll job status every 3 seconds while processing
  useEffect(() => {
    if (!polling || !job?.id) return;
    const interval = setInterval(async () => {
      try {
        const r = await api.get(`/jobs/${job.id}`);
        setJob(r.data);
        if (r.data.status === "COMPLETED") {
          setStep("done");
          setPolling(false);
        } else if (r.data.status === "FAILED") {
          setStep("error");
          setPolling(false);
        }
      } catch {
        clearInterval(interval);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [polling, job?.id]);

  const onDropSped = useCallback((files: File[]) => {
    const f = files[0];
    if (!f) return;
    if (!f.name.endsWith(".txt")) {
      toast.error("O arquivo SPED deve ser um .txt");
      return;
    }
    setSpedFile(f);
  }, []);

  const onDropExcel = useCallback((files: File[]) => {
    const f = files[0];
    if (!f) return;
    if (!f.name.match(/\.(xlsx|xls)$/)) {
      toast.error("A planilha deve ser .xlsx ou .xls");
      return;
    }
    setExcelFile(f);
  }, []);

  const { getRootProps: spedProps, getInputProps: spedInput, isDragActive: spedDrag } = useDropzone({
    onDrop: onDropSped,
    accept: { "text/plain": [".txt"] },
    maxFiles: 1,
  });

  const { getRootProps: xlProps, getInputProps: xlInput, isDragActive: xlDrag } = useDropzone({
    onDrop: onDropExcel,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
    },
    maxFiles: 1,
  });

  const canSubmit = selectedCompany && competencia && spedFile && excelFile;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      const [year, month] = competencia.split("-").map(Number);
      const periodStart = `${year}-${String(month).padStart(2, "0")}-01`;
      const lastDay = new Date(year, month, 0).getDate();
      const periodEnd = `${year}-${String(month).padStart(2, "0")}-${lastDay}`;

      // 1. Create job
      const jobRes = await api.post(`/companies/${selectedCompany}/jobs`, {
        period_start: periodStart,
        period_end: periodEnd,
      });
      const newJob: ProcessingJob = jobRes.data;
      setJob(newJob);

      // 2. Upload SPED
      const spedForm = new FormData();
      spedForm.append("file", spedFile!);
      await api.post(`/jobs/${newJob.id}/upload/sped`, spedForm, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      // 3. Upload Excel
      const xlForm = new FormData();
      xlForm.append("file", excelFile!);
      await api.post(`/jobs/${newJob.id}/upload/excel`, xlForm, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      // 4. Start processing
      await api.post(`/jobs/${newJob.id}/process`);

      setStep("processing");
      setPolling(true);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Erro ao iniciar processamento";
      toast.error(msg);
    }
  };

  const handleDownload = async () => {
    if (!job) return;
    try {
      const r = await api.get(`/jobs/${job.id}/download`);
      window.open(r.data.url, "_blank");
    } catch {
      toast.error("Erro ao obter link de download");
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Processar SPED ICMS</h1>
      <p className="text-gray-500 mb-8">
        Faça upload do arquivo SPED e da planilha SEFA-PA para inserir automaticamente os registros
        de antecipação de ICMS.
      </p>

      {step === "form" && (
        <div className="space-y-6">
          {/* Company + Period */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
            <h2 className="font-semibold text-gray-800">1. Selecione a empresa e competência</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Empresa</label>
                <select
                  value={selectedCompany}
                  onChange={(e) => setSelectedCompany(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                >
                  <option value="">Selecione...</option>
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Competência</label>
                <input
                  type="month"
                  value={competencia}
                  onChange={(e) => setCompetencia(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>
            </div>
          </div>

          {/* File uploads */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
            <h2 className="font-semibold text-gray-800">2. Faça upload dos arquivos</h2>

            <DropZone
              rootProps={spedProps()}
              inputProps={spedInput()}
              isDragActive={spedDrag}
              file={spedFile}
              label="Arquivo SPED EFD ICMS/IPI"
              hint=".txt gerado pelo sistema fiscal"
              icon="📄"
            />

            <DropZone
              rootProps={xlProps()}
              inputProps={xlInput()}
              isDragActive={xlDrag}
              file={excelFile}
              label="Planilha de Antecipações SEFA-PA"
              hint=".xlsx ou .xls baixado do portal SEFA-PA"
              icon="📊"
            />
          </div>

          {/* Checklist */}
          <div className="bg-gray-50 rounded-xl border border-gray-200 p-4 text-sm space-y-2">
            <CheckItem ok={!!selectedCompany} label={`Empresa: ${companies.find(c => c.id === selectedCompany)?.name ?? "—"}`} />
            <CheckItem ok={!!competencia} label={`Competência: ${competencia || "—"}`} />
            <CheckItem ok={!!spedFile} label={`SPED: ${spedFile?.name ?? "—"}`} />
            <CheckItem ok={!!excelFile} label={`Planilha: ${excelFile?.name ?? "—"}`} />
          </div>

          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-semibold py-3 px-6 rounded-xl transition"
          >
            <Upload className="w-5 h-5" />
            Iniciar Processamento
          </button>
        </div>
      )}

      {step === "processing" && (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center space-y-4">
          <Loader2 className="w-12 h-12 text-blue-600 animate-spin mx-auto" />
          <p className="text-lg font-semibold text-gray-800">Processando...</p>
          <p className="text-gray-500 text-sm">
            O sistema está inserindo os registros de antecipação no seu arquivo SPED.
            Isso pode levar alguns instantes.
          </p>
        </div>
      )}

      {step === "done" && job && (
        <div className="bg-white rounded-xl border border-green-200 p-8 space-y-6">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-8 h-8 text-green-600" />
            <div>
              <p className="text-lg font-bold text-gray-900">Processamento concluído!</p>
              <p className="text-sm text-gray-500">Seu arquivo SPED está pronto para download.</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 text-center text-sm">
            <Stat label="NFs encontradas" value={job.nfs_found ?? 0} />
            <Stat label="Antecipações vinculadas" value={job.anticipations_matched ?? 0} />
            <Stat label="Registros C197 inseridos" value={job.c197_records_inserted ?? 0} />
          </div>

          <button
            onClick={handleDownload}
            className="w-full flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 text-white font-semibold py-3 px-6 rounded-xl transition"
          >
            <Download className="w-5 h-5" />
            Baixar SPED Processado
          </button>
        </div>
      )}

      {step === "error" && job && (
        <div className="bg-white rounded-xl border border-red-200 p-8 space-y-4">
          <div className="flex items-center gap-3">
            <XCircle className="w-8 h-8 text-red-600" />
            <div>
              <p className="text-lg font-bold text-gray-900">Erro no processamento</p>
              <p className="text-sm text-gray-500">{job.error_message}</p>
            </div>
          </div>
          <button
            onClick={() => setStep("form")}
            className="bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium py-2 px-4 rounded-lg text-sm transition"
          >
            Tentar novamente
          </button>
        </div>
      )}
    </div>
  );
}

function DropZone({
  rootProps,
  inputProps,
  isDragActive,
  file,
  label,
  hint,
  icon,
}: {
  rootProps: object;
  inputProps: object;
  isDragActive: boolean;
  file: File | null;
  label: string;
  hint: string;
  icon: string;
}) {
  return (
    <div
      {...rootProps}
      className={cn(
        "border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors",
        isDragActive
          ? "border-blue-500 bg-blue-50"
          : file
          ? "border-green-400 bg-green-50"
          : "border-gray-300 hover:border-blue-400 hover:bg-gray-50"
      )}
    >
      <input {...inputProps} />
      <div className="text-3xl mb-2">{icon}</div>
      <p className="font-medium text-sm text-gray-700">{label}</p>
      {file ? (
        <p className="text-xs text-green-600 mt-1 font-medium">{file.name}</p>
      ) : (
        <p className="text-xs text-gray-400 mt-1">{hint} — clique ou arraste aqui</p>
      )}
    </div>
  );
}

function CheckItem({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className={ok ? "text-green-600" : "text-gray-300"}>
        {ok ? "✓" : "○"}
      </span>
      <span className={ok ? "text-gray-700" : "text-gray-400"}>{label}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3">
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  );
}
