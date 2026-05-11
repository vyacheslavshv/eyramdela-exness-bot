from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "users" ADD "email" VARCHAR(255);
        CREATE INDEX "idx_users_email_133a6f" ON "users" ("email");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_users_email_133a6f";
        ALTER TABLE "users" DROP COLUMN "email";"""


MODELS_STATE = (
    "eJztmutv2zYQwP8Vwp8yLAlS2Xls35zH2gxxMqTuVrQoBFqkZcISqZJUHijyv4+kJOut2p"
    "6fmL7ZvDuK/B3FOx71o+MzhD1x3A8RkXfM7fwOfnQo9LH6UZIdgg4MglSiGyQceUYZai3b"
    "i9VGQnLoSCUYQ09g1YSwcDgJJGFUq/eDAFN0xKj3CoSEEh8pAyqIlgPVCxgzDhAeha5LqA"
    "t+BRD5hAJCRYAdrXSsn4OYox6kFFbXZUjJ9xDbkrlYTjBXHX/9ppoJRfgFi+RvMLXHBHso"
    "x4sg3YFpt+VrYNpuqfzDKOrRjmyHeaFPU+XgVU4YnWkTKnWriynmagK6e8lDjY+GnhejTo"
    "hGI01VoiFmbBAew9DTTtDWJR8kjRmGcZPDqPafGo0wE3T1U46sd73z3kX3rHehVMxIZi3n"
    "b9H00rlHhobA/bDzZuRQwkjDYEy5Sexhl0PfrgJ4SdxahgXDn8NM0DXRTBrWjfM3y+p2z6"
    "2T7tnFae/8/PTiZMa1LGoCfHn7XjNWCky9c9HbmEBPIeMnHPHI472aQF4Nd2ZQwKqmsptY"
    "ffhie5i6cqL+nvUaiP3df7z60H88OOv9ksd2H0ssI8oDRFhC4pUJDvFLzfJMLZZCGPNpIJ"
    "juratB2IBsePPZLDFfiO9eFtXBoP/ZUPRfY8ndw/37RD2D9uru4bKA1OFYT9+GFQvzWkkk"
    "8XE12rxlAS+KTY+TH7u5XtUU0IMKVnHXTfBvBzcfh/3BXzkPXPeHN1pi5egnrQdnhbU96w"
    "T8czv8APRf8OXh/sYAZEK63Dwx1Rt+6egxwVAym7JnG6IMhaQ1IfWmo+J4mtnfdcMIOtNn"
    "yJFdkjCL1emWRb7lF1sgha7xioarhxknK4/Yg68DLAQ0u2wpmcnJGxMarjVtP1IV82U1Ax"
    "gIAHWioWeCUZRiHAmCMIh7AnqeQDKgsgvAOFG5CJQ6HwkF5uWkZiU9tjnNxnOamcNsX7gL"
    "JzZV1m1205Dd6KVuL51HVlmvC/eqY/Z2eO9X5F458zZ0ryF0fxImNJVCtmlvDNX6/Z0zQv"
    "fBMH7PTXhUMRNKMIECKN9ibapC7DORExNMR0xWlBmW6aGNwP/zqsKGaG4h7JrfJcD1dYWs"
    "zZ6ci/OlBev0dI7agtKqLS4YWZ7kmHAh7UVZ5q1amrNil19ZqmkodvnrrdSstda1FoSBwr"
    "DQWpwZ7OUy7FpzIOxatQS1qLAGX6g6n9thVfhpWIg5q5WgXHvoyYF8d3IyB0mlVYvSyPIs"
    "9XVOKBbhmFpsrHzdYXTEVBasWa3s1Z6njG3Vl7GtUhlbgeHLndzylu3JbQdOblnHPmFO1D"
    "yW8WzBdAWu3a27ix3yZDLtRld6UGV1zgQ70yWcWTJu3bkL7nyGnKoJL+vQvHnr0i27dEqc"
    "6VJbbc6wdeOW3ag/GNJvlSDUqTjsNLuyZNy6cxc2WscjmEp78SNDtfVenmatec5gVv0RzC"
    "qdwAycgDPtLmGPPehWsK3/FKbGfE/gbvq7GEMLYfV6EGlLJmFFLesaO8SHXgPuUgfF/Snq"
    "4Tjuad/IX99c3Q76dwfveodRWUZhJhJnV3ivehmr/hFeNhHLGrcb/pY3fD017ISSPCmXBM"
    "TGnDNesTHV3vXUd7C5+/+T/7Drr+AObUduf/uYE2fSqfr+PJIcNn59nur87Aq4Hm57Sbvx"
    "S9onzIUe0gJpWsZkXaXdPbzx0q/GAhBj9f0EuJYrBvVEWfmF/J8fH+5rg4es/kb+E1UT/I"
    "qIIw+BR4T8tptYGyjqWTfntcUUthDedQeX2w4vb/8CjAzo7Q=="
)
