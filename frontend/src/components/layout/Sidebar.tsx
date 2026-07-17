"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  FileText,
  Home,
  LayoutDashboard,
  LogOut,
  Settings,
  Upload,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { toast } from "sonner";

const navItems = [
  { href: "/dashboard", label: "Início", icon: Home, exact: true },
  { href: "/empresas", label: "Empresas", icon: Building2 },
  { href: "/processar", label: "Processar SPED", icon: Upload },
  { href: "/usuarios", label: "Usuários", icon: Users },
  { href: "/assinatura", label: "Assinatura", icon: Settings },
];

const adminNavItems = [
  { href: "/admin", label: "Painel Admin", icon: LayoutDashboard, exact: true },
  { href: "/admin/escritorios", label: "Escritórios", icon: Building2 },
  { href: "/admin/usuarios", label: "Usuários", icon: Users },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useCurrentUser();
  const items = user?.role === "ADMIN" ? adminNavItems : navItems;

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // ignore
    }
    localStorage.removeItem("access_token");
    router.push("/login");
    toast.success("Logout realizado");
  };

  return (
    <aside className="w-64 min-h-screen bg-gray-900 text-white flex flex-col">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-gray-700">
        <div className="w-9 h-9 bg-blue-500 rounded-lg flex items-center justify-center flex-shrink-0">
          <FileText className="w-5 h-5 text-white" />
        </div>
        <div>
          <p className="font-bold text-sm leading-tight">FacilitadorSped</p>
          <p className="text-xs text-gray-400">ICMS Antecipado PA</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {items.map(({ href, label, icon: Icon, exact }) => {
          const isActive = exact ? pathname === href : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                isActive
                  ? "bg-blue-600 text-white"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              )}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Logout */}
      <div className="px-3 py-4 border-t border-gray-700">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-gray-300 hover:bg-gray-800 hover:text-white transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Sair
        </button>
      </div>
    </aside>
  );
}
