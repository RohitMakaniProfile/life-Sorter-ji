import { RichMessage } from "../../../api/types";

export default function UserMessage({ message }: { message: RichMessage }) {
  return (
    <div className="px-4 py-2 bg-violet-600 text-white rounded-xl">
      {message.content}
    </div>
  );
}