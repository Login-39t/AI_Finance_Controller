import { redirect } from "next/navigation";

// The overview dashboard is the last screen to be built, not the first.
// Until it exists, land people where the work is.
export default function HomePage() {
  redirect("/exceptions");
}
