import Link from "next/link";
import { container, ctaPrimary } from "@/lib/site";

export default function NotFound() {
  return (
    <div className={`${container} py-20`}>
      <p className="kicker">§ 404</p>
      <h1 className="mt-2 font-serif text-4xl font-semibold">No page at this anchor.</h1>
      <p className="mt-3 max-w-md text-muted-foreground">
        The page or stored answer you asked for does not exist. A shared answer link may be mistyped, or the answer may
        have been removed.
      </p>
      <Link href="/ask" className={`${ctaPrimary} mt-8`}>
        Ask a question
      </Link>
    </div>
  );
}
