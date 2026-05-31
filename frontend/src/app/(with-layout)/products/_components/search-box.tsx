"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function SearchBox({ initialValue }: { initialValue: string }) {
  const router = useRouter();
  const [value, setValue] = useState(initialValue);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    router.push(q ? `/products?q=${encodeURIComponent(q)}` : "/products");
  };

  return (
    <form onSubmit={submit} className="flex gap-2">
      <input
        type="search"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Nom ou marque (min. 2 caractères)"
        className="flex-1 rounded-lg border border-stroke bg-transparent px-4 py-2.5 text-sm outline-none focus:border-primary dark:border-dark-3"
      />
      <button
        type="submit"
        className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white hover:opacity-90"
      >
        Rechercher
      </button>
    </form>
  );
}
