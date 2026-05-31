import { UploadForm } from "./_components/upload-form";

export const metadata = {
  title: "Upload ticket",
};

export default function TicketUploadPage() {
  return (
    <>
      <div className="mb-6">
        <h1 className="text-heading-4 font-bold text-dark dark:text-white">
          Uploader un ticket
        </h1>
        <p className="text-sm text-dark-6">
          Photographie ton ticket de caisse, on s&apos;occupe du reste.
        </p>
      </div>

      <UploadForm />
    </>
  );
}
