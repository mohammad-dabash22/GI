from docx import Document

def extract_comments_simple():
    try:
        doc = Document(r'd:\code\GI\reports\FIS_Graph_Intelligence_-_BRD_V0.2_DRAFT.docx')
        
        if hasattr(doc.part, 'comments'):
            comments = doc.part.comments
            with open('brd_comments.txt', 'w', encoding='utf-8') as f:
                f.write(f"Total Comments Found: {len(comments)}\n\n")
                for c in comments:
                    f.write(f"--- Comment ---\n")
                    f.write(f"Author: {c.author}\n")
                    f.write(f"Comment: {c.text}\n\n")
            print(f"Successfully extracted {len(comments)} comments to brd_comments.txt")
        else:
            print("doc.part has no 'comments' attribute.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")

if __name__ == "__main__":
    extract_comments_simple()
