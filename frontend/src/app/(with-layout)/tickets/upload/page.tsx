import { UploadForm } from "./_components/upload-form";

export const metadata = {
  title: "Ajouter un ticket",
};

export default function TicketUploadPage() {
  return (
    <>
      <div className="mb-6">
        <h1 className="text-heading-4 font-bold text-dark dark:text-white">
          Ajouter un ticket
        </h1>
        <p className="text-sm text-dark-6">
          Photographiez votre ticket de caisse. La lecture des articles est
          automatique ; vous pourrez la vérifier juste après.
        </p>
      </div>

      <UploadForm />
    </>
  );
}
